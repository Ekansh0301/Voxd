#!/usr/bin/env python3
"""
Generate a nested directory tree structure for the flash-copilot project.
Usage: python3 a.py [--max-depth N] [--show-hidden] [--count-lines]
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

# Directories and files to exclude
EXCLUDE_DIRS = {
    'venv', 'env', '__pycache__', '.git', '.venv',
    '.pytest_cache', '.tox', 'dist', 'build', '*.egg-info',
    'node_modules', '.mypy_cache', '.ruff_cache'
}

EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.so', '.o', '.a'}

class TreeGenerator:
    def __init__(self, root_path: str, max_depth: int = None, 
                 show_hidden: bool = False, count_lines: bool = False):
        self.root_path = Path(root_path)
        self.max_depth = max_depth
        self.show_hidden = show_hidden
        self.count_lines = count_lines
        self.total_dirs = 0
        self.total_files = 0
        self.total_lines = 0
    
    def should_exclude(self, name: str, is_dir: bool) -> bool:
        """Check if path should be excluded."""
        if not self.show_hidden and name.startswith('.'):
            return True
        if name in EXCLUDE_DIRS:
            return True
        ext = Path(name).suffix
        if ext in EXCLUDE_EXTENSIONS:
            return True
        return False
    
    def count_lines_in_file(self, filepath: Path) -> int:
        """Count lines in a file (for Python files)."""
        if filepath.suffix not in {'.py', '.json', '.sh', '.md'}:
            return 0
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return len(f.readlines())
        except:
            return 0
    
    def generate_tree(self, path: Path = None, prefix: str = "", 
                     depth: int = 0) -> str:
        """Recursively generate tree structure."""
        if path is None:
            path = self.root_path
        
        # Check depth limit
        if self.max_depth is not None and depth > self.max_depth:
            return ""
        
        try:
            items = sorted(path.iterdir(), 
                          key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return f"{prefix}[Permission Denied]\n"
        
        # Filter excluded items
        items = [item for item in items 
                if not self.should_exclude(item.name, item.is_dir())]
        
        tree_str = ""
        for i, item in enumerate(items):
            is_last = (i == len(items) - 1)
            current_prefix = "└── " if is_last else "├── "
            next_prefix = "    " if is_last else "│   "
            
            if item.is_dir():
                self.total_dirs += 1
                tree_str += f"{prefix}{current_prefix}{item.name}/\n"
                if self.max_depth is None or depth < self.max_depth:
                    tree_str += self.generate_tree(
                        item, 
                        prefix + next_prefix, 
                        depth + 1
                    )
            else:
                self.total_files += 1
                size_str = ""
                size_bytes = item.stat().st_size
                if size_bytes > 1024 * 1024:
                    size_str = f" ({size_bytes / (1024*1024):.1f}MB)"
                elif size_bytes > 1024:
                    size_str = f" ({size_bytes / 1024:.1f}KB)"
                
                lines_str = ""
                if self.count_lines and item.suffix == '.py':
                    lines = self.count_lines_in_file(item)
                    self.total_lines += lines
                    lines_str = f" [{lines} lines]"
                
                tree_str += f"{prefix}{current_prefix}{item.name}{size_str}{lines_str}\n"
        
        return tree_str
    
    def run(self):
        """Generate and print the tree."""
        print(f"\n📁 Tree: {self.root_path.name}/\n")
        tree = self.generate_tree()
        print(tree)
        
        # Print summary
        print("─" * 60)
        print(f"📊 Summary:")
        print(f"   Directories: {self.total_dirs}")
        print(f"   Files: {self.total_files}")
        if self.count_lines:
            print(f"   Python LOC: {self.total_lines}")
        print("─" * 60 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate a nested directory tree"
    )
    parser.add_argument(
        '--root', '-r',
        default='.',
        help='Root directory to scan (default: current directory)'
    )
    parser.add_argument(
        '--max-depth', '-d',
        type=int,
        default=None,
        help='Maximum directory depth to show'
    )
    parser.add_argument(
        '--show-hidden',
        action='store_true',
        help='Show hidden files/folders'
    )
    parser.add_argument(
        '--count-lines',
        action='store_true',
        help='Count lines in Python files'
    )
    
    args = parser.parse_args()
    
    generator = TreeGenerator(
        root_path=args.root,
        max_depth=args.max_depth,
        show_hidden=args.show_hidden,
        count_lines=args.count_lines
    )
    generator.run()


if __name__ == "__main__":
    main()