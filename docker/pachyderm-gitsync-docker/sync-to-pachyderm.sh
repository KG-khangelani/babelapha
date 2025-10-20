#!/bin/bash
set -euo pipefail

echo '=== Pachyderm GitSync Container ==='
echo ''

# Environment variables (provided by TeamCity or docker run)
GITHUB_REPO_URL=${GITHUB_REPO_URL:-https://github.com/KG-khangelani/babelapha.git}
GITHUB_BRANCH=${GITHUB_BRANCH:-main}
GITHUB_TOKEN=${GITHUB_TOKEN:-}
PACHYDERM_REPO=${PACHYDERM_REPO:-babelapha-source}
PACHYDERM_BRANCH=${PACHYDERM_BRANCH:-master}
PACHD_ADDRESS=${PACHD_ADDRESS:-pachd.pachyderm.svc.cluster.local:30650}
PACHYDERM_AUTH_TOKEN=${PACHYDERM_AUTH_TOKEN:-}
SOURCE_DIR=${SOURCE_DIR:-pipelines/pachyderm}
BUILD_NUMBER=${BUILD_NUMBER:-1}
BUILD_VCS_NUMBER=${BUILD_VCS_NUMBER:-unknown}

export PACHD_ADDRESS

echo 'Configuration:'
echo "  GitHub Repo: ${GITHUB_REPO_URL}"
echo "  GitHub Branch: ${GITHUB_BRANCH}"
echo "  Pachyderm Repo: ${PACHYDERM_REPO}"
echo "  Source Directory: ${SOURCE_DIR}"
echo "  Build #${BUILD_NUMBER} (Commit: ${BUILD_VCS_NUMBER})"
echo ''

# Authenticate with Pachyderm
if [ -n "${PACHYDERM_AUTH_TOKEN}" ]; then
    echo 'Authenticating with Pachyderm...'
    echo "${PACHYDERM_AUTH_TOKEN}" | pachctl auth use-auth-token
else
    echo 'Warning: No PACHYDERM_AUTH_TOKEN provided'
fi

# Verify connection
echo 'Verifying Pachyderm connection...'
if pachctl version 2>/dev/null; then
    echo '✓ Connected to Pachyderm'
else
    echo '✗ Cannot connect to Pachyderm'
    exit 1
fi

# Clone the repository
echo ''
echo 'Cloning repository...'
CLONE_DIR="/tmp/repo"
rm -rf "${CLONE_DIR}"

if [ -n "${GITHUB_TOKEN}" ]; then
    # Clone with token for private repos
    REPO_URL_WITH_TOKEN=$(echo "${GITHUB_REPO_URL}" | sed "s|https://|https://${GITHUB_TOKEN}@|")
    git clone --depth 1 --branch "${GITHUB_BRANCH}" "${REPO_URL_WITH_TOKEN}" "${CLONE_DIR}"
else
    git clone --depth 1 --branch "${GITHUB_BRANCH}" "${GITHUB_REPO_URL}" "${CLONE_DIR}"
fi

cd "${CLONE_DIR}"
echo '✓ Repository cloned'

# Check if source directory exists
if [ ! -d "${SOURCE_DIR}" ]; then
    echo "✗ Error: Source directory '${SOURCE_DIR}' not found in repository"
    echo 'Available directories:'
    find . -type d -maxdepth 3
    exit 1
fi

echo "✓ Found source directory: ${SOURCE_DIR}"

# Create commit message
COMMIT_MSG="TeamCity Build #${BUILD_NUMBER} - Commit: ${BUILD_VCS_NUMBER}"

# Put files into Pachyderm
echo ''
echo "Syncing '${SOURCE_DIR}' to Pachyderm..."
pachctl put file ${PACHYDERM_REPO}@${PACHYDERM_BRANCH}:/ -r -f "${SOURCE_DIR}" --message "${COMMIT_MSG}"

# Add commit metadata
echo ''
echo 'Adding commit metadata...'
git log -1 --pretty=format:'Repository: %H%nAuthor: %an <%ae>%nDate: %ad%nMessage: %s' > /tmp/commit_info.txt
echo "" >> /tmp/commit_info.txt
echo "TeamCity Build: #${BUILD_NUMBER}" >> /tmp/commit_info.txt
echo "Synced at: $(date)" >> /tmp/commit_info.txt

pachctl put file ${PACHYDERM_REPO}@${PACHYDERM_BRANCH}:/commit_info.txt -f /tmp/commit_info.txt

echo ''
echo '✓ Successfully synced to Pachyderm!'
echo ''
echo 'Recent commits in Pachyderm:'
pachctl list commit ${PACHYDERM_REPO} | head -5

echo ''
echo 'Files in Pachyderm:'
pachctl list file ${PACHYDERM_REPO}@${PACHYDERM_BRANCH}:/
