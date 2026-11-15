mock_provider "aws" {
  mock_resource "aws_vpc" {
    defaults = {
      ipv6_cidr_block = "2001:db8:1234:5600::/56"
    }
  }
}

variables {
  name = "nursing-ai-test"
}

run "no_nat_gateway" {
  assert {
    condition     = aws_route.ipv6_egress.destination_ipv6_cidr_block == "::/0"
    error_message = "the only route must be the IPv6 default route"
  }
  assert {
    condition     = aws_route.ipv6_egress.nat_gateway_id == null && aws_route.ipv6_egress.gateway_id == null
    error_message = "the route must not use a NAT or internet gateway"
  }
  assert {
    condition     = aws_route.ipv6_egress.destination_cidr_block == null
    error_message = "there must be no IPv4 route"
  }
  assert {
    condition     = length(aws_route_table.private.route) == 0
    error_message = "the route table must carry no inline routes"
  }
  assert {
    condition     = alltrue([for s in aws_subnet.private : s.map_public_ip_on_launch == false])
    error_message = "no subnet may hand out public IPv4 addresses"
  }
}

run "egress_only_gateway_routes_ipv6" {
  assert {
    condition     = aws_route.ipv6_egress.egress_only_gateway_id == aws_egress_only_internet_gateway.this.id
    error_message = "the route must go through the egress-only gateway"
  }
  assert {
    condition     = aws_route.ipv6_egress.route_table_id == aws_route_table.private.id
    error_message = "the route must sit on the private route table"
  }
  assert {
    condition     = length(aws_route_table_association.private) == 2
    error_message = "every subnet needs a route table association"
  }
  assert {
    condition = alltrue([
      for a in aws_route_table_association.private : a.route_table_id == aws_route_table.private.id
    ])
    error_message = "every subnet must use the private route table"
  }
  assert {
    condition = toset([for a in aws_route_table_association.private : a.subnet_id]) == toset([
      for s in aws_subnet.private : s.id
    ])
    error_message = "every subnet must be associated"
  }
}

run "subnets_are_dual_stack_in_two_azs" {
  assert {
    condition     = aws_vpc.this.assign_generated_ipv6_cidr_block == true
    error_message = "the VPC must ask AWS for an IPv6 block"
  }
  assert {
    condition     = aws_vpc.this.enable_dns_support == true && aws_vpc.this.enable_dns_hostnames == true
    error_message = "DNS support and hostnames must be on"
  }
  assert {
    condition     = aws_subnet.private[0].cidr_block == "10.0.0.0/24" && aws_subnet.private[1].cidr_block == "10.0.1.0/24"
    error_message = "the subnets must take consecutive /24s from the VPC range"
  }
  assert {
    condition     = output.private_subnet_ids[0] == aws_subnet.private[0].id && aws_subnet.private[0].availability_zone == "ap-southeast-2a"
    error_message = "the subnet ids must come out in zone order"
  }
  assert {
    condition     = length(aws_default_security_group.this.ingress) == 0 && length(aws_default_security_group.this.egress) == 0
    error_message = "the default security group must have no rules"
  }
  assert {
    condition     = length(aws_subnet.private) == 2
    error_message = "expected two subnets"
  }
  assert {
    condition     = length(toset([for s in aws_subnet.private : s.availability_zone])) == 2
    error_message = "the subnets must sit in different zones"
  }
  assert {
    condition = toset([for s in aws_subnet.private : s.ipv6_cidr_block]) == toset([
      "2001:db8:1234:5600::/64",
      "2001:db8:1234:5601::/64",
    ])
    error_message = "each subnet must take a /64 from the VPC's IPv6 block"
  }
  assert {
    condition     = alltrue([for s in aws_subnet.private : s.assign_ipv6_address_on_creation])
    error_message = "IPv6 auto-assign must be on"
  }
  assert {
    condition     = output.ipv6_cidr_block == "2001:db8:1234:5600::/56"
    error_message = "the output must expose the VPC's IPv6 block"
  }
}

run "database_only_reachable_from_the_app" {
  assert {
    condition     = aws_vpc_security_group_ingress_rule.db_from_app.from_port == 5432 && aws_vpc_security_group_ingress_rule.db_from_app.to_port == 5432 && aws_vpc_security_group_ingress_rule.db_from_app.ip_protocol == "tcp"
    error_message = "the database must accept TCP 5432 only"
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.db_from_app.referenced_security_group_id == aws_security_group.app.id
    error_message = "the database must accept traffic from the app group only"
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.db_from_app.security_group_id == aws_security_group.db.id
    error_message = "the rule must belong to the database group"
  }
  assert {
    condition     = length(aws_security_group.db.ingress) == 0 && length(aws_security_group.db.egress) == 0
    error_message = "the database group must have no inline rules"
  }
  assert {
    condition     = aws_vpc_security_group_egress_rule.app_to_db.referenced_security_group_id == aws_security_group.db.id && aws_vpc_security_group_egress_rule.app_to_db.from_port == 5432 && aws_vpc_security_group_egress_rule.app_to_db.to_port == 5432 && aws_vpc_security_group_egress_rule.app_to_db.ip_protocol == "tcp"
    error_message = "the app may reach the database on 5432"
  }
  assert {
    condition     = aws_vpc_security_group_egress_rule.app_https_ipv6.cidr_ipv6 == "::/0" && aws_vpc_security_group_egress_rule.app_https_ipv6.from_port == 443 && aws_vpc_security_group_egress_rule.app_https_ipv6.to_port == 443 && aws_vpc_security_group_egress_rule.app_https_ipv6.ip_protocol == "tcp" && aws_vpc_security_group_egress_rule.app_https_ipv6.cidr_ipv4 == null
    error_message = "the app may reach the internet over IPv6 on 443 only"
  }
}

run "one_az_is_refused" {
  command = plan

  variables {
    availability_zones = ["ap-southeast-2a"]
  }

  expect_failures = [var.availability_zones]
}

run "duplicate_azs_are_refused" {
  command = plan

  variables {
    availability_zones = ["ap-southeast-2a", "ap-southeast-2a"]
  }

  expect_failures = [var.availability_zones]
}
