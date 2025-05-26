provider "aws" {
  region = var.aws_region
}

resource "aws_instance" "ado_migration_instance" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  iam_instance_profile   = var.instance_profile
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.ado_migration_sg.id]
  user_data              = file("user_data.sh")

  ebs_block_device {
    device_name           = "/dev/sda1"
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true

    tags = {
      Name        = "${var.project_name}-${var.environment}-ado-migration-ebs"
      Environment = var.environment
      Project     = var.project_name
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-ado-migration-instance"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_security_group" "ado_migration_sg" {
  name        = "${var.project_name}-${var.environment}-ado-migration-sg"
  description = "Security group for ADO migration instance"
  vpc_id      = var.vpc_id

  #   ingress = {
  #     from_port   = 80
  #     to_port     = 80
  #     protocol    = "tcp"
  #     cidr_blocks = ["0.0.0/0"]
  #   }

  # Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-ado-migration-sg"
    Environment = var.environment
    Project     = var.project_name
  }

}