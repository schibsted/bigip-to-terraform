# bigip-2-terraform

Transform running F5 BigIP config into Terraform resources.

(C) 2022 Nicolai Langfeldt nicolai.langfeldt@schibsted.com.  This code
is developed on Schibsteds time and dime.

This is Open Source with a Apache2 license.  See COPYING.md

Contributions welcome: please make a PR.

## Usage

This script covers three use cases

- `./runner -u`: list unreferenced pool and node resources to help you
  see what can be removed from your BigIP configuration.
- `./runner -v <vipspec>`: Pick out data from your BigIP to construct a
  terraform config to configure the VIP, pool and nodes needed for the
  specified VIP(s).  Vipspec can be a /regular expression/ or just a
  'substring'. It will be searched for in the VIP name, the VIP "fullpath"
  (which includes /Common or other partition name) and the destination,
  i.e. the IP of the VIP.
  All matching VIPs and their pool and node resources
  will be extracted.  Adds to terraform state already present in the
  `terraformer` directory.
- `./runner` - just extract all of it.  By default this also documents
  the unreferenced resources.  Clears any previous state.  This can be
  quite time consuming depending on your configuration size.

Add `-c` to clear the terraform state before importing the newly
discovered resources.

Running with `-v` is additive (unless you do `-c`) so you can export
all the VIPs and attendant resources you'd like.

If you run several times in a way that results in overlapping VIP,
pool or node resources that will result in a conflict and the import
of the resources will be ungraciously aborted mid stream.

## Installing requirements

You will need Python 3 and pip.  And also terraform, at least version
0.13 from what I can see.

```
pip install -r requirements.txt

```

## Restrictions

- Only tested with a /Common partition.  If you use partitions you
  may need to debug and fix some.
- The script only handles VIPs, pools and nodes.  Policies and other
  things are not handled.  Patches welcome.
- I also assume this will break if you have some IPv6.  We _do_ have
  some IPv6 VIPs but I would not consider this well tested.

## Running

In the root directory create login.json with contents like this:

```json
{
    "bigip": "172.16.17.18",
    "user": "someuser",
    "password": "the-password"
}
```

The user can be a "audit" user, it does not need r/w permissions on
the BigIP.

Now execute `./runner` as described in Usage above. Unless you specify
`-u` this will:

1. run the python script that dumps the resources we (I) care about:
   VIPs, pools and nodes.
1. Skeleton declarations for the resources are written to `import.tf`
   and then copied to the `terraformer` directory.
1. In the `import.tf` file are embedded comments that contain the
   commands to import all the resources from the running BigIP to the
   local `terraform.tfstate` file. These commands are executed.
1. When all the resources are imported into the terraform state it is
   used to generate `resources.tf` which contain the full resource
   declarations for your use.
1. Finaly `import.tf` is deleted from the terraformer directory and a
   `importer-<time-date>.tf` is left in the root directory.

After all this you should be able to use terraform to configure your
BigIP, either for the resources you specified with `-v` or the whole
config.

If you grep for "not referenced" in the `importer-<time-date>.tf` file
you will get a list of pools and nodes that are not in use.  You can
delete these from your BigIP if you like.
