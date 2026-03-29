#!/bin/bash
set -e

echo "🐳 1/4: Updating package list..."
apt-get update

echo "🐳 2/4: Installing prerequisites..."
apt-get install -y ca-certificates curl gnupg lsb-release

echo "🐳 3/4: Adding Docker's official GPG key and repository..."
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "🐳 4/4: Installing Docker Engine and Docker Compose Plugin..."
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "✅ Docker installation successful!"
docker --version
docker compose version
