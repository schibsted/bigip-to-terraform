# f5-2-terraform

Dump F5 configuration to terraform format

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

Now execute `./runner`.  This will:

1. run the python script that dumps the resources we (I) care about:
   VIPs, pools and nodes.
1. Skeleton declarations for the resources are written to `import.tf`
   and then copied to the `terraformer` directory.
1. In the `import.tf` file are embedded comments that contain the
   commands to import all the resources from the running BigIP to the
   local `terraform.tfstate` file.
1. When all the resources are imported into the terraform state it is
   used to generate `resources.tf` which contain the full resource
   declarations for your use.
1. Finaly `import.tf` is deleted from the terraformer directory and a
   `importer-<time-date>.tf` is left in the root directory.

After all this you should be able to use terraform to configure your
BigIP.

If you grep for "not referenced" in the `importer-<time-date>.tf` file
you will get a list of pools and nodes that are not in use.  You can
delete these from your BigIP if you like.


