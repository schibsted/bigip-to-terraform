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
import json
from pprint import pprint
from f5.bigip import ManagementRoot


def printAttr(object, lead, attr):
    '''Print the attribute of object in terraform format if it exists'''

    if hasattr(object, attr):
        value = eval(f"object.{attr}")
        if type(value) is list:
            print(f"  {lead:18s} = {value}")
        else:
            print(f"  {lead:18s} = \"{value}\"")

def terrify(name):
    '''Make a name terraform compliant by tr/[A-Z]-/[a-z]_/'''
    name=name.lower()
    return re.sub(r'[-/:]', '_', name)

# Chat with BigIP 

def login():
    with open('login.json', 'r+') as f:
        data = json.load(f)
        bigip    = data['bigip']
        username = data['user']
        password = data['password']

    # Connect to the BigIP
    return ManagementRoot(bigip, username, password)


def process_vips(vips):
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

    members = {}

    for pool in pools:
        if not used_pools.get(pool.fullPath):
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
    be defined and also need to define the attachment of nodes to pools.

    Each member looks like this:
    {'address': '10.1.1.1',
     'connectionLimit': 0,
     'dynamicRatio': 1,
     'ephemeral': 'false',
     'fqdn': {'autopopulate': 'disabled'},
     'fullPath': '/Common/some-server:80',
     'generation': 1,
     'inheritProfile': 'enabled',
     'kind': 'tm:ltm:pool:members:membersstate',
     'logging': 'disabled',
     'monitor': 'default',
     'name': 'some-server:80',
     'partition': 'Common',
     'priorityGroup': 0,
     'rateLimit': 'disabled',
     'ratio': 1,
     'slfLink': 'https://localhost/mgmt/tm/ltm/pool/~Common~server_core/members/~Common~some-server:80?ver=15.1.8',
     'session': 'monitor-enabled',
     'state': 'up'}

    '''

    nodes_done = {}

    # Matches the hostname of "some_server:443"
    no_port = re.compile('^[^:]*')

    pool_members = {}

    # Now first output all the nodes
    for pool in members.keys():

        pool_members[pool] = []

        for nodek in members[pool].keys():
            node = members[pool][nodek]
            
            tname = terrify(node.name)
            # Just the nodename, with no port
            just_node = no_port.match(node.name).group()
            node_path = no_port.match(node.fullPath).group()

            pool_members[pool].append(node.fullPath)

            if nodes_done.get(just_node):
                # If this node has already been seen don't print it again
                continue

            nodes_done[just_node] = True

            thisNode = members[pool][nodek]
        
            print(f"resource \"bigip_ltm_node\" \"{just_node}\" {{")
            printAttr(thisNode,"name","fullPath")
            print("}")
            print()
            print(f"#import# terraform import bigip_ltm_node.{just_node} {node_path}")
            print()

    return pool_members


def process_attachments(pools, used_pools, pool_members):
    '''From a dictionary of pools attach the nodes that are members of
    each pool.'''

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


def main():
    mgmt = login()

    # used_pools = process_vips(mgmt.tm.ltm.virtuals.get_collection())
    
    used_pools={'/Common/varnish_core': True}

    all_pools = mgmt.tm.ltm.pools.get_collection()
    
    members = process_pools(all_pools, used_pools)

    pool_members = process_members(members)

    process_attachments(all_pools, used_pools, pool_members)



main()
