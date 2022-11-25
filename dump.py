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

# These relate to user options and change script behaviour
only_vip = ''
make_resources = True
show_unref = True

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


def print_vip(vip):
    global make_resources

    if make_resources:
        tname=terrify(vip.name)
        print()
        print(f"resource \"bigip_ltm_virtual_server\" \"{tname}\" {{")
        printAttr(vip,"name","fullPath")
        print("}")
        print()

        print(f"#import# terraform import bigip_ltm_virtual_server.{tname} {vip.fullPath}")
        print()


def process_vips(vips):
    global only_vip

    print("* Processing VIPs", file=sys.stderr)
    used_pools = {}
    for vip in vips:
        # If there is a VIP filter find out if it matches.
        if only_vip:
            if type(only_vip) is re.Pattern:
                if not (only_vip.search(vip.fullPath) or
                        only_vip.search(vip.name) or
                        only_vip.search(vip.destination)):
                   continue
            elif type(only_vip) is str:
                if not (vip.fullPath.find(only_vip) > 0 or
                        vip.name.find(only_vip or
                        vip.destination.find(only_vip)) > 0):
                    continue

        if hasattr(vip, 'pool'):
            used_pools[vip.pool] = True
        print_vip(vip)

    return used_pools


def print_pool(pool):
    global make_resources

    if make_resources:
        tname = terrify(pool.name)
        print(f"resource \"bigip_ltm_pool\" \"{tname}\" {{")
        printAttr(pool,"name","fullPath")
        print("}")
        print()
        print(f"#import# terraform import bigip_ltm_pool.{tname} {pool.fullPath}")
        print(f"#sed# /pool/ s~\"{pool.fullPath}\"~resource.bigip_ltm_pool.{tname}.name~;")
        print()


def process_pools(pools, used_pools):
    '''Get a list of all pools on the BigIP and print their names and their
    members' names.'''

    print("* Processing pools", file=sys.stderr)

    members = {}

    for pool in pools:
        if not used_pools.get(pool.fullPath):
            if show_unref:
                print(f"# Pool not referenced: {pool.fullPath}")
                print()

            continue

        print_pool(pool)

        members[pool.fullPath] = {}

        # Save all the pool members
        for member in pool.members_s.get_collection():
            # Using the selfLink as identifier as the same node at
            # the same port can potentially be used in multiple
            # pools. The selfLink contains the pool name.
            members[pool.fullPath][member.selfLink] = member

    return members


def print_node(node, name, path):
    global make_resources

    if make_resources:
        tname = terrify(name)

        print(f"resource \"bigip_ltm_node\" \"{tname}\" {{")
        printAttr(node,"name","fullPath")
        print("}")
        print()
        print(f"#import# terraform import bigip_ltm_node.{tname} {path}")
        print(f"#sed# /node/ s~\"{path}:~\"${{resource.bigip_ltm_node.{tname}.name}}:~;")
        print()


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

            # print(f"Going to print {node.fullPath} {node_path} ?", file=sys.stderr)

            if nodes_done.get(node_path):
                # print("not", file=sys.stderr)
                # If this node has already been seen don't print it again
                continue

            pool_members[pool].append(node.fullPath)

            nodes_done[node_path] = True
            # print("now done:",nodes_done, file=sys.stderr)

            print_node(members[pool][nodek], just_node, node_path)

    return pool_members, nodes_done


def process_attachments(pools, used_pools, pool_members):
    '''From a dictionary of pools attach the nodes that are members of
    each pool.'''

    global make_resources

    print("* Attaching nodes to pools", file=sys.stderr)

    node_used = {}

    for pool in pools:
        if not used_pools.get(pool.fullPath):
            continue

        for node in pool_members[pool.fullPath]:
            tname = terrify(pool.name + node)

            if make_resources:
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

        if show_unref:
            print(f"# Node not referenced: {node.fullPath}");


def process_vip_filter(filter):
    '''Figure out if it's a regex or just a substring'''
    if filter[0] == '/':
        # It's a regular expression, strip the surounding // and use it
        return re.compile(filter[1:-1])

    return filter


def main():
    global only_vip
    global make_resources
    global show_unref

    try:
        opts, args = getopt.getopt(sys.argv[1:], "v:cu",
                                   ["vip=", "clear", "unreferenced"])
    except getopt.GetoptError as err:
        print(err)
        usage()
        exit(2)

    for o, a in opts:
        if o == '-v':
            only_vip = process_vip_filter(a)
            show_unref = False
        if o == '-c':
            # noop for us
            True
        if o == '-u':
            make_resources = False

    if not show_unref and not make_resources:
        print("Nothing to do!", file=sys.stderr)
        usage()
        exit(2)

    mgmt = login()

    used_pools = process_vips(mgmt.tm.ltm.virtuals.get_collection())
    all_pools = mgmt.tm.ltm.pools.get_collection()
    members = process_pools(all_pools, used_pools)
    pool_members, nodes_used = process_members(members)
    process_attachments(all_pools, used_pools, pool_members)
    all_nodes = mgmt.tm.ltm.nodes.get_collection()
    list_unused_nodes(nodes_used, all_nodes)


main()
