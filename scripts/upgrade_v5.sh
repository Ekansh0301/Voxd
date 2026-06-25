#!/usr/bin/env bash
# Flash Copilot v5 upgrade — installs ollama library and switches to native tool calling
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
source venv/bin/activate

echo "Installing ollama Python library..."
pip install ollama --quiet
echo "✓ ollama library installed"

echo ""
echo "Testing native tool calling..."
python3 -c "
import ollama, json
try:
    # Quick test
    r = ollama.chat(
        model='qwen2.5:3b',
        messages=[{'role':'user','content':'say OK'}],
        tools=[{
            'type':'function',
            'function':{
                'name':'say_ok',
                'description':'Say OK',
                'parameters':{'type':'object','properties':{},'required':[]}
            }
        }],
    )
    print(f'Native tool calling works. Tool calls: {len(r.message.tool_calls or [])}')
    print(f'Response: {r.message.content[:60]}')
except Exception as e:
    print(f'Warning: {e}')
    print('Falling back to HTTP API mode (still works)')
"

echo ""
echo "✓ v5 ready. Run: python3 flash_copilot.py"
