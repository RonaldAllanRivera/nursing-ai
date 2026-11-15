# A dual-stack VPC with private subnets only. There is no NAT gateway and no
# internet gateway: the only way out is IPv6, through an egress-only gateway,
# which refuses connections that start outside.

resource "aws_vpc" "this" {
  cidr_block                       = var.cidr_block
  assign_generated_ipv6_cidr_block = true
  enable_dns_support               = true
  enable_dns_hostnames             = true

  tags = {
    Name = var.name
  }
}

# The default security group allows everything inside the VPC. Declaring it
# with no rules removes all of them, so nothing can use it by accident.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name}-default-locked"
  }
}

resource "aws_subnet" "private" {
  count = length(var.availability_zones)

  vpc_id                          = aws_vpc.this.id
  availability_zone               = var.availability_zones[count.index]
  cidr_block                      = cidrsubnet(var.cidr_block, 8, count.index)
  ipv6_cidr_block                 = cidrsubnet(aws_vpc.this.ipv6_cidr_block, 8, count.index)
  assign_ipv6_address_on_creation = true
  map_public_ip_on_launch         = false

  tags = {
    Name = "${var.name}-private-${var.availability_zones[count.index]}"
  }
}

resource "aws_egress_only_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = var.name
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.name}-private"
  }
}

resource "aws_route" "ipv6_egress" {
  route_table_id              = aws_route_table.private.id
  destination_ipv6_cidr_block = "::/0"
  egress_only_gateway_id      = aws_egress_only_internet_gateway.this.id
}

resource "aws_route_table_association" "private" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "app" {
  name_prefix = "${var.name}-app-"
  description = "The Lambda functions: outbound HTTPS over IPv6 and the database, nothing inbound"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${var.name}-app"
  }

  # A replacement must create the new group first: a group in use by Lambda
  # network interfaces cannot be deleted until they move.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "db" {
  name_prefix = "${var.name}-db-"
  description = "The Aurora cluster: reachable only from the app security group"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${var.name}-db"
  }

  # A replacement must create the new group first: a group in use by Lambda
  # network interfaces cannot be deleted until they move.
  lifecycle {
    create_before_destroy = true
  }
}

# The Lambdas call Anthropic, Google, SQS and SSM, and those addresses change,
# so the rule cannot name them. There is no IPv4 route out, and the egress-only
# gateway refuses connections from outside.
#trivy:ignore:AWS-0104
resource "aws_vpc_security_group_egress_rule" "app_https_ipv6" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS to the internet over IPv6"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv6         = "::/0"
}

resource "aws_vpc_security_group_egress_rule" "app_to_db" {
  security_group_id            = aws_security_group.app.id
  description                  = "PostgreSQL to the database"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.db.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the app"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.app.id
}
