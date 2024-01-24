terraform {
  required_providers {
    bigip = {
      # source = "F5Networks/bigip"
      source = "terraform.local/local/bigip"
      version = ">= 1.17"
    }
  }
}

provider "bigip" {
  address  = var.hostname
  username = var.username
  password = var.password
}
