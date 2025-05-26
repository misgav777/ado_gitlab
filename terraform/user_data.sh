#!/bin/bash
sudo apt-get update
sudo apt-getupgrade -y
# Install Docker and Docker Compose
sudo apt-get install -y docker.io docker-compose
sudo curl -L "    https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
# Add the current user to the docker group
sudo usermod -aG docker $USER
# Enable and start Docker service
sudo systemctl enable docker
sudo systemctl start docker
