#!/usr/bin/env python3
'''Exfiltrate things from BigIP iControl REST api to build proximal
terraform files to rebuild them from scratch.

Proximal because this is not well tested (remember to do "terraform
plan"!) and also because we don't even try to reproduce all the
attributes, there will have to be a "terraform import" of each object
to get the state from the BigIP before even trying to do a plan or
apply.

NOTE: We only use the /Common parition, if you use partitioning you'll
have some development on your hands

NOTE: This only collects the VIPs, the Pools and the Nodes.  We'll
assume policies and everything else needed is already present in the
BigIP.

NOTE: I assume this will break on IPv6.

'''

import re
import sys
import json
import getopt
from pprint import pprint
from f5.bigip import ManagementRoot

def printAttr(object, lead, attr):
    '''Print the attribute of object in terraform format if it exists'''

    if hasattr(object, attr):
        value = eval(f"object.{attr}")
        if type(value) is list:
            print(f"  {lead:10s} = {value}")
        else:
            print(f"  {lead:10s} = \"{value}\"")

def terrify(name):
    '''Make a name terraform compliant identifier'''
    name=name.lower()
    # Replace illegal chars with _
    name=re.sub(r'[^-a-zA-Z0-9_]', '_', name)
    # Add a leading x if the name starts in something non-alpha
    if re.match(r'^[^a-zA-Z]', name):
        return "x" + name

    return name


# Chat with BigIP 

def login():
    with open('login.json', 'r+') as f:
        data = json.load(f)
        bigip    = data['bigip']
        username = data['user']
        password = data['password']

    # Connect to the BigIP
    return ManagementRoot(bigip, username, password)


def process_vips(vips,filter):
    print("* Processing VIPs", file=sys.stderr)
    used_pools = {}
    for vip in vips:
        tname=terrify(vip.name)
        print(f"resource \"bigip_ltm_virtual_server\" \"{tname}\" {{")
        printAttr(vip,"name","fullPath")
        if hasattr(vip, 'pool'):
            used_pools[vip.pool] = True
        print("}")
        print()

        print(f"#import# terraform import bigip_ltm_virtual_server.{tname} {vip.fullPath}")
        print()

    return used_pools


def process_pools(pools, used_pools):
    '''Get a list of all pools on the BigIP and print their names and their
    members' names.'''

    print("* Processing pools", file=sys.stderr)

    members = {}

    for pool in pools:
        if not used_pools.get(pool.fullPath):
            print(f"# Pool not referenced: {pool.fullPath}")
            print()
            continue
        
        tname = terrify(pool.name)
        print(f"resource \"bigip_ltm_pool\" \"{tname}\" {{")
        printAttr(pool,"name","fullPath")
        print("}")
        print()
        print(f"#import# terraform import bigip_ltm_pool.{tname} {pool.fullPath}")
        print()

        members[pool.fullPath] = {}

        # Save all the pool members
        for member in pool.members_s.get_collection():
            # Using the selfLink as identifier as the same node at
            # the same port can potentially be used in multiple
            # pools. The selfLink contains the pool name.
            members[pool.fullPath][member.selfLink] = member

    return members


def process_members(members):
    '''From the pools we collected all the pool members. Now they need to
    be defined and also need to define the attachment of nodes to pools.'''

    print("* Processing nodes", file=sys.stderr)

    nodes_done = {}

    # Matches the hostname of "some_server:443"
    no_port = re.compile('^[^:]*')

    pool_members = {}

    # Now first output all the nodes
    for pool in members.keys():

        pool_members[pool] = []

        for nodek in members[pool].keys():
            node = members[pool][nodek]
            
            # Just the nodename, with no port
            just_node = no_port.match(node.name).group()
            node_path = no_port.match(node.fullPath).group()

            tname = terrify(just_node)

            if tname == 'x' or tname == '':
                print("FATAL! I have no name for this node", file=sys.stderr)
                print(f"just_node: {just_node} path: {node_path}", file=sys.stderr)
                print(node.attrs, file=sys.stderr)
                exit(1)

            pool_members[pool].append(node.fullPath)

            if nodes_done.get(node_path):
                # If this node has already been seen don't print it again
                continue

            nodes_done[node_path] = True

            thisNode = members[pool][nodek]
        
            print(f"resource \"bigip_ltm_node\" \"{tname}\" {{")
            printAttr(thisNode,"name","fullPath")
            print("}")
            print()
            print(f"#import# terraform import bigip_ltm_node.{tname} {node_path}")
            print()

    return pool_members, nodes_done


def process_attachments(pools, used_pools, pool_members):
    '''From a dictionary of pools attach the nodes that are members of
    each pool.'''

    print("* Attaching nodes to pools", file=sys.stderr)

    node_used = {}

    for pool in pools:
        if not used_pools.get(pool.fullPath):
            continue

        for node in pool_members[pool.fullPath]:
            tname = terrify(pool.name + node)

            print(f"resource \"bigip_ltm_pool_attachment\" \"{tname}\" {{")
            printAttr(pool, "pool", "fullPath")
            print("}")
            print()
            print(f"#import# terraform import bigip_ltm_pool_attachment.{tname}"
                  f" '{{\"pool\": \"{pool.fullPath}\", \"node\": \"{node}\"}}'")
            print()


def list_unused_nodes(used, all):
    '''In the end list the nodes that are not referenced by any used pools'''

    for node in all:
        if used.get(node.fullPath):
            # Node was used in config
            continue

        print(f"# Node not referenced: {node.fullPath}");


def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "v:c", ["vip=","clear"])
    except getopt.GetoptError as err:
        print(err)
        usage()
        exit(2)

    only_vip = ''

    for o, a in opts:
        if o == '-v':
            only_vip = a
        if o == '-c':
            only_vip = ''
            # noop for us
    
    mgmt = login()

    used_pools = process_vips(mgmt.tm.ltm.virtuals.get_collection(), only_vip)
    
    all_pools = mgmt.tm.ltm.pools.get_collection()
    
    members = process_pools(all_pools, used_pools)

    pool_members, nodes_used = process_members(members)

    process_attachments(all_pools, used_pools, pool_members)

    all_nodes = mgmt.tm.ltm.nodes.get_collection()

    list_unused_nodes(nodes_used, all_nodes)


main()
