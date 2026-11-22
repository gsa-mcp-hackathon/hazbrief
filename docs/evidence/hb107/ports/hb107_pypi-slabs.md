---
created: 2026-11-06T11:17:38 (UTC -05:00)
tags: []
source: https://pypi.org/project/slabs/
title: slabs · PyPI
---

# slabs · PyPI

# slabs 1.0.3

Automated network lab provisioning on GCP with containerlab and netlab

```
pip install slabs
```

Released: Apr 30, 2026 (2026-04-30 14:15:24 +00:00)

## Project description

Simple Labs

CLI tool for managing network lab environments on Google Cloud Platform (GCP). Creates VMs with nested virtualization support for running containerized network devices.

### Features

- GCP VM Management: Create, start, stop, suspend, resume, delete, and list VMs
- Nested Virtualization: Enabled by default for running containers/VMs inside the lab VM
- IP Forwarding: Enabled for network traffic handling
- Automatic Zone Fallback: Tries other zones in the region if resources are exhausted
- Flexible Authentication: Supports gcloud CLI, service account keys, or environment variables

### Architecture

- Single GCP VM (n1-standard-4 or larger) with nested virtualization
- Ubuntu 22.04 LTS base image
- Automatic zone selection within configured region

### How it fits together

```
YOUR MAC GOOGLE CLOUD (europe-west3)
┌──────────────────┐ ┌─────────────────────────────────────────────┐
│ │ │ │
│ slabs CLI │ ──── GCP API (HTTPS) ───▶ │ Compute Engine VM (n1-standard-4) │
│ (Click + uv) │ create / start / … │ Ubuntu 22.04 + nested virtualization │
│ │ │ ┌───────────────────────────────────────┐ │
│ ~/.ssh/ │ ──── SSH (paramiko) ────▶ │ │ netlab → containerlab → docker │ │
│ simplelabs │ deploy topology.yml │ └───────────────────────────────────────┘ │
│ │ │ │ │
│ WireGuard app │ ◀═══ WG tunnel :51820 ═══▶ │ clab bridge │
│ │ (UDP, encrypted) │ 192.168.121.0/24 (mgmt) │
└──────────────────┘ │ │ │
│ ┌─────┬───────┴───────┬─────┐ │
│ ▼ ▼ ▼ ▼ │
│ ┌───┐ ┌───┐ ┌───┐ ┌───┐ │
│ │r1 │ │r2 │ ... │s1 │ │s2 │ │
│ └───┘ └───┘ └───┘ └───┘ │
│ Arista cEOS / Linux containers │
│ (OSPF, iBGP/eBGP, VRFs, VLANs, STP) │
└─────────────────────────────────────────────┘
```

Flow

1. slabs vm create — provisions the VM via the Compute Engine API, auto-installs Docker / Containerlab / netlab / Ansible through the startup script.
2. slabs lab deploy — uploads a netlab topology YAML over SSH; netlab up renders it into a containerlab spec and launches the containers.
3. slabs vpn setup — installs WireGuard on the VM, opens UDP/51820 in the GCP firewall and hands back a client config for your Mac.
4. From your Mac you can ping/ssh straight into any lab device on the clab mgmt subnet.

### Project Structure

```
simple-labs/
├── slabs/ # Main Python package
│ ├── cli.py # CLI entry point (`slabs` command)
│ ├── gcp/
│ │ └── compute.py # VM provisioning and management
│ └── utils/
│ └── config.py # Configuration loading
├── labs/examples/ # Example configurations
│ └── config.yml # Configuration template
├── pyproject.toml # Package configuration
└── README.md
```

### Quick Start

#### 1. Install Dependencies

```
uv sync
```

#### 2. Authenticate with GCP

```
gcloud auth application-default login
```

#### 3. Configure

Copy the example config and customize:

```
cp labs/examples/config.yml labs/my-config.yml
```

Edit labs/my-config.yml:

```
gcp_project_id: your-project-id
gcp_zone: europe-west3-a
gcp_region: europe-west3
vm_machine_type: n1-standard-4 # n1 required for nested virtualization
vm_disk_size_gb: 100
```

#### 4. Create a VM with Tools

Create a VM and automatically install all required tools (Docker, Containerlab, Ansible, Netlab):

```
# Create VM with --wait-ready to wait for tool installation to complete
uv run slabs vm create --name my-lab-vm --wait-ready

# Or create without waiting (check status later)
uv run slabs vm create --name my-lab-vm

# Check setup status anytime
uv run slabs vm setup-status --name my-lab-vm
```

The --wait-ready flag monitors the VM setup and reports success or failure with logs.

#### 5. Deploy a Lab

Once the VM is ready, deploy a network lab topology:

```
# Deploy the example 3-device lab
uv run slabs lab deploy --vm my-lab-vm --topology labs/examples/simple-lab.yml --wait

# Check lab status
uv run slabs lab status --vm my-lab-vm

# Stop the lab when done
uv run slabs lab stop --vm my-lab-vm
```

#### 6. Manage VMs

```
# List all VMs
uv run slabs vm list --config labs/my-config.yml

# Stop a VM
uv run slabs vm stop --name my-lab-vm --config labs/my-config.yml

# Start a VM
uv run slabs vm start --name my-lab-vm --config labs/my-config.yml

# Delete a VM
uv run slabs vm delete --name my-lab-vm --config labs/my-config.yml
```

### Full Workflow Example

```
# 1. Authenticate
gcloud auth application-default login

# 2. Create VM with tools (wait for completion)
uv run slabs vm create --name lab-vm --wait-ready

# 3. Deploy a lab
uv run slabs lab deploy --vm lab-vm --topology labs/examples/simple-lab.yml --wait

# 4. Check lab is running
uv run slabs lab status --vm lab-vm

# 5. SSH into VM to work with the lab
ssh -i ~/.ssh/simplelabs ubuntu@<vm-ip>

# 6. Stop the lab (keeps VM running)
uv run slabs lab stop --vm lab-vm

# 7. Or stop the VM entirely
uv run slabs vm stop --name lab-vm

# 8. Resume later
uv run slabs vm start --name lab-vm

# 9. Clean up when done
uv run slabs vm delete --name lab-vm
```

### Tools Installed on VM

When creating a VM with tool installation enabled (default), the following are automatically installed:

- Docker - Container runtime
- Containerlab - Network lab orchestration tool
- Python 3.11 - With pip and virtualenv
- Ansible - Configuration management
- Netlab - Network lab topology management

Disable with --no-tools flag if you want a bare VM.

### CLI Commands

#### slabs vm create

Create a new VM with nested virtualization enabled. Tools are installed by default.

```
uv run slabs vm create --name <vm-name> [options]
```

Options:

```
-n, --name TEXT VM instance name (required)
-z, --zone TEXT GCP zone (overrides config)
-m, --machine-type TEXT Machine type (default: n1-standard-4)
-d, --disk-size INTEGER Disk size in GB
--no-nested-virt Disable nested virtualization
--no-ip-forward Disable IP forwarding
--no-tools Skip tool installation (Docker, containerlab, etc.)
--wait-ready, -w Wait for tool setup to complete
-c, --config PATH Path to config file
```

#### slabs vm setup-status

Check the tool installation status on a VM.

```
uv run slabs vm setup-status --name <vm-name>
```

Shows whether setup is running, complete, or failed (with error logs).

#### slabs vm list

List all VMs in the project with their status and external IPs.

```
uv run slabs vm list [--config PATH]
```

#### slabs vm start|stop|suspend|resume|delete

Manage existing VMs by name.

```
uv run slabs vm start --name <vm-name> [--config PATH]
uv run slabs vm stop --name <vm-name> [--config PATH]
uv run slabs vm suspend --name <vm-name> [--config PATH]
uv run slabs vm resume --name <vm-name> [--config PATH]
uv run slabs vm delete --name <vm-name> [--config PATH]
```

#### slabs lab deploy

Deploy a network lab topology to a VM.

```
uv run slabs lab deploy --vm <vm-name> --topology <path-to-yml> [options]
```

Options:

```
-v, --vm TEXT VM name (required)
-t, --topology PATH Path to topology YAML file (required)
-n, --name TEXT Lab name (default: "default")
-w, --wait Wait for VM to be ready before deploying
-c, --config PATH Path to config file
```

#### slabs lab status

Check the status of a deployed lab.

```
uv run slabs lab status --vm <vm-name> [--name <lab-name>]
```

Shows number of containers running and their states.

#### slabs lab stop

Stop a running lab (destroy containers but keep files).

```
uv run slabs lab stop --vm <vm-name> [--name <lab-name>]
```

#### slabs vpn setup

Install and configure a WireGuard VPN server on the VM so you can reach lab devices from your local machine.

```
uv run slabs vpn setup --vm <vm-name> [--output <path>] [--routes <cidrs>]
```

Options:

- --output, -o - Where to save the client config (default: ./wireguard-client.conf)
- --routes - Comma-separated CIDRs routed through the VPN (default: 192.168.121.0/24,10.0.0.0/16)
- --no-firewall - Skip creating the GCP firewall rule

Example:

```
# 1. Create VM and deploy lab first
uv run slabs vm create --name lab-vm --wait-ready
uv run slabs lab deploy --vm lab-vm --topology labs/tests/arista-ospf-bgp.yml

# 2. Install WireGuard server and download client config
uv run slabs vpn setup --vm lab-vm --output ~/Downloads/lab-vpn.conf

# 3. On your Mac: install WireGuard from App Store,
# import ~/Downloads/lab-vpn.conf, activate tunnel

# 4. Reach the lab devices directly
ping 192.168.121.101
ssh admin@192.168.121.101
```

#### slabs vpn status

Show WireGuard peer status and handshake info from the VM.

```
uv run slabs vpn status --vm <vm-name>
```

#### slabs vpn get-config

Re-download the existing client config (useful after VM IP change or losing the file).

```
uv run slabs vpn get-config --vm <vm-name> --output ./lab-vpn.conf
```

#### slabs lab imgload

Load a Docker image from a local tar.gz file to the VM.

```
uv run slabs lab imgload --vm <vm-name> --image <path-to-tar.gz>
```

Example:

```
# Load ceos image to the VM
uv run slabs lab imgload --vm lab-vm --image images/ceos-4.34.5M.tar.gz
```

This uploads the image and runs docker load on the VM.

### Authentication

Choose one of the following methods:

gcloud CLI (recommended for local development):

```
gcloud auth application-default login
```

Service Account Key (for CI/CD):

```
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

Config file:

```
gcp_credentials_path: /path/to/service-account-key.json
```

### SSH Key Management

Simple Labs uses SSH keys to deploy labs and manage VMs remotely. The CLI handles this automatically, but you can also manage keys manually.

#### Automatic Key Generation

When you create a VM, Simple Labs automatically generates an SSH key pair at ~/.ssh/simplelabs (if it doesn't exist) and injects the public key into the VM:

```
# Key is auto-generated during VM creation
uv run slabs vm create --name my-lab-vm

# The key is then used automatically for lab operations
uv run slabs lab deploy --vm my-lab-vm --topology labs/examples/simple-lab.yml
```

#### Manual Key Generation

To create the SSH key pair manually (optional):

```
# Generate Ed25519 key pair
ssh-keygen -t ed25519 -f ~/.ssh/simplelabs -N "" -C "simplelabs-key"

# This creates:
# ~/.ssh/simplelabs (private key)
# ~/.ssh/simplelabs.pub (public key)

# Set correct permissions
chmod 600 ~/.ssh/simplelabs
chmod 644 ~/.ssh/simplelabs.pub
```

#### Custom Key Path

To use a different SSH key:

```
# 1. Generate key at custom location
ssh-keygen -t ed25519 -f ~/.ssh/my-lab-key -N ""

# 2. Update config.yml
ssh_key_path: ~/.ssh/my-lab-key
ssh_username: ubuntu

# 3. Or use environment variables
export SSH_KEY_PATH=~/.ssh/my-lab-key
export SSH_USERNAME=ubuntu
```

#### Manual SSH Access

To SSH into a VM manually using the generated key:

```
ssh -i ~/.ssh/simplelabs ubuntu@<vm-external-ip>
```

#### Troubleshooting

Permission denied (publickey):

- Ensure the VM was created with --wait or enough time has passed for the startup script to complete
- Verify the public key was injected: check VM metadata in GCP Console
- Check SSH key permissions: chmod 600 ~/.ssh/simplelabs

Key not found:

- Run ssh-keygen to manually create the key
- Or simply run uv run slabs vm create - it will auto-generate the key

### Requirements

- Python 3.11+
- UV package manager
- GCP project with:
  - Compute Engine API enabled
  - Billing enabled
  - Appropriate quotas for n1 machine types

### Development Commands

```
# Install dependencies
uv sync

# Run CLI
uv run slabs --help

# Add dependency
uv add <package>

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .
```

### License

This project is licensed under the MIT License - see the [LICENSE](https://gitlab.com/netodata/simple-labs/-/blob/main/LICENSE) file for details.

Built and maintained by NETODATA — network automation, done right.

## Sidebar

### Project links

Data verified by PyPI on Apr 30, 2026

- [Changelog](https://gitlab.com/netodata/simple-labs/-/blob/main/CHANGELOG.md)
- [Homepage](https://gitlab.com/netodata/simple-labs)
- [Issues](https://gitlab.com/netodata/simple-labs/-/issues)
- [Repository](https://gitlab.com/netodata/simple-labs)

### Key dates

PyPI data

Released: Apr 30, 2026

LATEST RELEASE

### 1 maintainer

PyPI data

netodata_io

### Credits

Author: Milan Zapletal

### GitLab Statistics

Data verified by PyPI on Apr 30, 2026

[Repository](https://gitlab.com/netodata/simple-labs)

- Stars: 0
- Forks: 0
- Open issues: 0
- Open merge requests: 0

### License expression

MIT

View SPDX License List

### Requires

Python >=3.11

### Provides Extra

dev test

### Tags

automation cli containerlab gcp google-cloud netlab network-lab networking wireguard

### Classifiers

- Development Status
  - 4 - Beta
- Environment
  - Console
- Intended Audience
  - Developers
  - System Administrators
  - Telecommunications Industry
- Operating System
  - MacOS
  - POSIX :: Linux
- Programming Language
  - Python :: 3
  - Python :: 3 :: Only
  - Python :: 3.11
  - Python :: 3.12
  - Python :: 3.13
- Topic
  - Software Development :: Libraries :: Python Modules
  - System :: Networking
  - System :: Systems Administration
- Typing
  - Typed
