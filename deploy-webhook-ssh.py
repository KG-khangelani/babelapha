#!/usr/bin/env python3
"""
SSH deployment helper for Pachyderm → Airflow webhook
Copies deployment script to control node and executes it
"""

import subprocess
import argparse
import sys
from pathlib import Path

def run_command(cmd, description=""):
    """Run command and return success status."""
    if description:
        print(f"\n[*] {description}")
    print(f"  Command: {cmd}")
    result = subprocess.run(cmd, shell=True)
    return result.returncode == 0

def main():
    parser = argparse.ArgumentParser(
        description="Deploy Pachyderm webhook on control node via SSH"
    )
    parser.add_argument(
        "--user",
        default="khangelani",
        help="SSH user (default: khangelani)"
    )
    parser.add_argument(
        "--host",
        default="192.168.10.104",
        help="Control node IP (default: 192.168.10.104)"
    )
    parser.add_argument(
        "--key",
        help="SSH private key path (optional)"
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Copy files but don't execute"
    )
    
    args = parser.parse_args()
    
    SSH_USER = args.user
    SSH_HOST = args.host
    SSH_ADDR = f"{SSH_USER}@{SSH_HOST}"
    
    print("=" * 60)
    print("  Pachyderm → Airflow Webhook Deployment")
    print("=" * 60)
    print(f"\nTarget: {SSH_ADDR}")
    print()
    
    # Build SSH command prefix
    ssh_cmd_prefix = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10"
    if args.key:
        ssh_cmd_prefix += f" -i {args.key}"
    ssh_cmd_prefix += f" {SSH_ADDR}"
    
    # Step 1: Verify SSH connectivity
    print("[1/3] Verifying SSH connectivity...")
    if not run_command(f"{ssh_cmd_prefix} 'echo OK'"):
        print(f"ERROR: Cannot SSH to {SSH_ADDR}")
        print("Verify:")
        print(f"  1. Host is reachable: ping {SSH_HOST}")
        print(f"  2. SSH key configured: ssh-add (if using key auth)")
        print(f"  3. User has kubectl access")
        sys.exit(1)
    print("✓ SSH connection successful")
    
    # Step 2: Copy deployment script
    print("\n[2/3] Copying deployment script to control node...")
    local_script = Path(__file__).parent / "deploy-webhook-on-cluster.sh"
    if not local_script.exists():
        print(f"ERROR: {local_script} not found")
        sys.exit(1)
    
    if not run_command(
        f"scp -o StrictHostKeyChecking=no {local_script} {SSH_ADDR}:~/",
        "Uploading deployment script"
    ):
        print("ERROR: Failed to copy script")
        sys.exit(1)
    print("✓ Script copied")
    
    # Step 3: Execute deployment
    if args.no_execute:
        print("\n[3/3] Skipping execution (--no-execute)")
        print(f"\nTo deploy, run on control node:")
        print(f"  ssh {SSH_ADDR}")
        print(f"  bash ~/deploy-webhook-on-cluster.sh")
        sys.exit(0)
    
    print("\n[3/3] Executing deployment script...")
    print()
    
    # Run the deployment script on control node
    cmd = f"{ssh_cmd_prefix} 'bash ~/deploy-webhook-on-cluster.sh'"
    result = subprocess.run(cmd, shell=True)
    
    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("  ✓ DEPLOYMENT SUCCESSFUL")
        print("=" * 60)
        print("\nWebhook is now active. To test:")
        print("  1. Upload a file to Pachyderm:")
        print("     pachctl put file media@master:/incoming/test-001/test.mp4 -f sample.mp4")
        print("")
        print("  2. Watch webhook logs:")
        print("     kubectl -n airflow logs -l app=pachyderm-webhook -f")
        print("")
        print("  3. Check Airflow UI:")
        print("     kubectl -n airflow port-forward svc/airflow-webserver 8080:8080")
        print("     Open http://localhost:8080/dags/ingest_pipeline")
    else:
        print("\n" + "=" * 60)
        print("  ✗ DEPLOYMENT FAILED")
        print("=" * 60)
        print("\nCheck SSH output above for errors")
        sys.exit(1)

if __name__ == "__main__":
    main()
