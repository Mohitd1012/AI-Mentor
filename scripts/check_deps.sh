#!/usr/bin/env bash
# Verify all required dependencies are present.

OK=true
check() {
  local name="$1"; local cmd="$2"
  if eval "$cmd" &>/dev/null; then
    echo "  ✓ $name"
  else
    echo "  ✗ $name — NOT FOUND"
    OK=false
  fi
}

echo "Checking AI Mentor dependencies..."
check "Node.js 18+"   "node --version | grep -E 'v(1[89]|[2-9][0-9])'"
check "npm"           "npm --version"
check "Rust/cargo"    "cargo --version"
check "Python 3.11+"  "python3 -c 'import sys; assert sys.version_info >= (3,11)'"
check "Ollama"        "ollama --version"
check "Ollama models" "ollama list | grep -v '^NAME'"

if $OK; then
  echo -e "\nAll dependencies satisfied ✓"
else
  echo -e "\nSome dependencies are missing. See above ✗"
  exit 1
fi
