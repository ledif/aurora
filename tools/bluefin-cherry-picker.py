#!/usr/bin/env python3
"""
Cherry-picking tool for syncing changes between Aurora and Bluefin projects.
"""

import argparse
import subprocess
import sys
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any
import re

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax
from rich.progress import track
from rich.columns import Columns
from rich import box

console = Console()


class GitRepo:
    """Helper class for Git operations."""
    
    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
    
    def run_git_command(self, command: List[str], capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command and return the result."""
        full_command = ["git", "-C", self.repo_path] + command
        try:
            result = subprocess.run(
                full_command, 
                capture_output=capture_output, 
                text=True, 
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            if check:
                print(f"Git command failed: {' '.join(full_command)}")
                print(f"Error: {e.stderr}")
                sys.exit(1)
            else:
                raise e
    
    def has_remote(self, remote_name: str) -> bool:
        """Check if a remote exists."""
        try:
            result = self.run_git_command(["remote"])
            return remote_name in result.stdout.split('\n')
        except:
            return False
    
    def add_remote(self, remote_name: str, remote_url: str) -> None:
        """Add a new remote."""
        console.print(f"[blue]Adding remote[/blue] [bold]{remote_name}[/bold] [dim]-> {remote_url}[/dim]")
        self.run_git_command(["remote", "add", remote_name, remote_url])
    
    def fetch_remote(self, remote_name: str) -> None:
        """Fetch from a remote."""
        with console.status(f"[cyan]Fetching from remote '{remote_name}'...", spinner="dots"):
            self.run_git_command(["fetch", remote_name])
    
    def get_commits_since(self, remote_branch: str, days: int, exclude_author: str = None) -> List[Dict[str, Any]]:
        """Get commits from a remote branch since N days ago."""
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # Format: commit_hash|author|date|subject
        format_str = "%H|%an|%ai|%s"
        command = [
            "log", 
            f"--since={since_date}",
            f"--pretty=format:{format_str}",
            remote_branch
        ]
        
        result = self.run_git_command(command)
        
        commits = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = line.split('|', 3)
                if len(parts) == 4:
                    # Filter out excluded authors
                    if exclude_author and exclude_author in parts[1]:
                        continue
                    commits.append({
                        'hash': parts[0],
                        'author': parts[1],
                        'date': parts[2],
                        'subject': parts[3]
                    })
        
        return commits
    
    def get_commit_file_changes(self, commit_hash: str) -> Dict[str, Any]:
        """Get the files changed in a commit."""
        try:
            # Get files changed in the commit
            result = self.run_git_command([
                "diff-tree", "--no-commit-id", "--name-status", "-r", commit_hash
            ])
            
            changes = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.strip().split('\t', 1)
                    if len(parts) == 2:
                        status, filepath = parts
                        change_type = {
                            'A': 'added',
                            'M': 'modified', 
                            'D': 'deleted',
                            'R': 'renamed',
                            'C': 'copied'
                        }.get(status[0], 'changed')
                        changes.append({
                            'file': filepath,
                            'status': change_type
                        })
            
            return {'files': changes}
        except Exception as e:
            return {'files': [], 'error': str(e)}
    
    def extract_pr_url(self, commit_subject: str, project: str = "bluefin") -> str:
        """Extract PR URL from commit subject if it contains a PR number."""
        # Look for patterns like (#1234) or (ublue-os/bluefin#1234)
        pr_match = re.search(r'#(\d+)\)', commit_subject)
        if pr_match:
            pr_number = pr_match.group(1)
            return f"https://github.com/ublue-os/{project}/pull/{pr_number}"
        
        return ""

    def get_commit_diff(self, commit_hash: str) -> str:
        """Get the diff for a commit."""
        try:
            result = self.run_git_command([
                "show", "--no-merges", "--format=", commit_hash
            ])
            return result.stdout.strip()
        except Exception as e:
            return f"Error getting diff: {e}"

    def can_cherry_pick_cleanly(self, commit_hash: str) -> Dict[str, Any]:
        """Test if a commit can be cherry-picked cleanly using git merge-tree."""
        try:
            # Get the parent of the commit
            parent_result = self.run_git_command(["rev-parse", f"{commit_hash}^"])
            parent_hash = parent_result.stdout.strip()
            
            # Use git merge-tree to test the merge without actually doing it
            try:
                merge_result = self.run_git_command([
                    "merge-tree", 
                    parent_hash, 
                    "HEAD", 
                    commit_hash
                ], check=False)
                
                # Parse merge-tree output to find conflicts
                conflicts = []
                if merge_result.stdout.strip():
                    # Parse the merge-tree output for conflict markers
                    lines = merge_result.stdout.split('\n')
                    current_file = None
                    
                    for line in lines:
                        if line.startswith('@@'):
                            # Extract filename from diff header
                            if current_file:
                                conflicts.append(current_file)
                        elif line.startswith('+++') or line.startswith('---'):
                            # Extract filename
                            if line.startswith('+++') and line != '+++ /dev/null':
                                current_file = line[6:]  # Remove '+++ b/'
                        elif '<<<<<<<' in line or '>>>>>>>' in line or '=======' in line:
                            # Found conflict markers
                            if current_file and current_file not in conflicts:
                                conflicts.append(current_file)
                
                has_conflicts = len(conflicts) > 0
                
                return {
                    'can_apply': not has_conflicts,
                    'conflicts': conflicts,
                    'method': 'merge-tree'
                }
                
            except subprocess.CalledProcessError:
                # Fallback: just return unknown status
                return {
                    'can_apply': False,
                    'conflicts': [],
                    'method': 'unknown',
                    'error': 'Could not test with merge-tree'
                }
                
        except Exception as e:
            return {
                'can_apply': False,
                'conflicts': [],
                'error': str(e)
            }
    
    def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = self.run_git_command(["branch", "--show-current"])
        return result.stdout.strip()
    
    def get_conflict_files(self) -> List[str]:
        """Get list of files with conflicts."""
        try:
            result = self.run_git_command(["diff", "--name-only", "--diff-filter=U"])
            return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
        except:
            return []


class CherryPickerTool:
    """Main tool class for cherry-picking operations."""
    
    def __init__(self, our_project: str = "aurora"):
        self.our_project = our_project.lower()
        self.other_project = "bluefin" if our_project.lower() == "aurora" else "aurora"
        self.git = GitRepo()
        
        # Remote configuration
        if self.other_project == "bluefin":
            self.remote_url = "https://github.com/ublue-os/bluefin.git"
        else:
            self.remote_url = "https://github.com/ublue-os/aurora.git"
    
    def setup_remote(self) -> None:
        """Ensure the remote is set up and fetch latest changes."""
        if not self.git.has_remote(self.other_project):
            self.git.add_remote(self.other_project, self.remote_url)
        
        self.git.fetch_remote(self.other_project)
    
    def show_status(self, days: int = 7, test_compatibility: bool = True, show_diffs: bool = False) -> None:
        """Show status of commits that could be cherry-picked."""
        self.setup_remote()
        
        # Header panel
        header_text = f"[bold cyan]Looking for {self.other_project} commits from the last {days} days[/bold cyan]\n"
        header_text += f"[dim]Remote: {self.remote_url}[/dim]"
        console.print(Panel(header_text, title="[bold blue]Cherry-Pick Analysis[/bold blue]", border_style="blue"))
        
        # Get commits from the other project's main branch
        remote_branch = f"{self.other_project}/main"
        commits = self.git.get_commits_since(remote_branch, days)
        
        # Filter out bot commits
        bot_authors = ["ubot-7274[bot]", "renovate[bot]", "github-actions[bot]", 
                      "dependabot[bot]", "blacksmith-sh[bot]"]
        
        filtered_commits = []
        for commit in commits:
            if not any(bot in commit['author'] for bot in bot_authors):
                filtered_commits.append(commit)
        
        if not filtered_commits:
            if commits:
                console.print(f"[green]✅ No non-bot commits found in {self.other_project} from the last {days} days.[/green]")
                console.print(f"[dim]📊 Found {len(commits)} total commits, but all were from bots.[/dim]")
            else:
                console.print(f"[green]✅ No commits found in {self.other_project} from the last {days} days.[/green]")
            return
        
        # Summary panel
        summary_text = f"[bold green]{len(filtered_commits)}[/bold green] non-bot commits found"
        if len(commits) > len(filtered_commits):
            summary_text += f" [dim](out of {len(commits)} total)[/dim]"
        console.print(Panel(summary_text, title="[bold green]Summary[/bold green]", border_style="green"))
        
        # Process commits with progress bar if there are many
        commits_to_process = track(filtered_commits, description="[cyan]Analyzing commits...") if len(filtered_commits) > 3 else filtered_commits
        
        for i, commit in enumerate(commits_to_process, 1):
            self._display_commit_rich(commit, i, test_compatibility, show_diffs)

    def _display_commit_rich(self, commit: Dict[str, Any], index: int, test_compatibility: bool, show_diffs: bool) -> None:
        """Display a single commit with rich formatting."""
        # Create commit info table
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Field", style="bold blue", width=12)
        table.add_column("Value", style="white")
        
        # Basic commit info
        commit_hash = commit['hash'][:8]
        table.add_row("Commit", f"[yellow]{commit_hash}[/yellow]")
        table.add_row("Author", f"[cyan]{commit['author']}[/cyan]")
        table.add_row("Date", f"[dim]{commit['date'][:19]}[/dim]")
        
        # Show PR URL if available
        pr_url = self.git.extract_pr_url(commit['subject'], self.other_project)
        if pr_url:
            table.add_row("PR", f"[link={pr_url}]{pr_url}[/link]")
        
        # Show files changed
        file_changes = self.git.get_commit_file_changes(commit['hash'])
        if file_changes.get('files'):
            files_count = len(file_changes['files'])
            files_text = f"[bold]{files_count}[/bold] file{'s' if files_count != 1 else ''} changed"
            
            # Show file details
            file_details = []
            for change in file_changes['files'][:5]:  # Show first 5 files
                status_color = {
                    'added': 'green',
                    'modified': 'yellow', 
                    'deleted': 'red',
                    'renamed': 'blue',
                    'copied': 'magenta'
                }.get(change['status'], 'white')
                file_details.append(f"[{status_color}]{change['status']}[/{status_color}]: [dim]{change['file']}[/dim]")
            
            if files_count > 5:
                file_details.append(f"[dim]... and {files_count - 5} more[/dim]")
            
            files_text += "\n" + "\n".join(file_details)
            table.add_row("Files", files_text)
        
        # Test compatibility if requested
        if test_compatibility:
            with console.status("[cyan]Testing cherry-pick compatibility...", spinner="dots"):
                compatibility = self.git.can_cherry_pick_cleanly(commit['hash'])
            
            if compatibility['can_apply']:
                status_text = "[green]✅ CAN APPLY CLEANLY[/green]"
            else:
                status_text = "[red]❌ CONFLICTS EXPECTED[/red]"
                if compatibility.get('conflicts'):
                    status_text += f"\n[red]💥 Conflicted files:[/red] [dim]{', '.join(compatibility['conflicts'])}[/dim]"
                if compatibility.get('error'):
                    status_text += f"\n[yellow]⚠️ Error:[/yellow] [dim]{compatibility['error']}[/dim]"
            
            table.add_row("Status", status_text)
        
        # Cherry-pick command
        table.add_row("Command", f"[green]git cherry-pick {commit['hash']}[/green]")
        
        # Create the panel with commit subject as title
        title = f"[bold white][{index}] {commit['subject'][:60]}{'...' if len(commit['subject']) > 60 else ''}[/bold white]"
        console.print(Panel(table, title=title, border_style="bright_blue"))
        
        # Show diff if requested
        if show_diffs:
            diff = self.git.get_commit_diff(commit['hash'])
            if diff:
                self._display_diff_with_rich(diff)
            else:
                console.print("[dim]Unable to retrieve diff[/dim]")
        
        console.print()  # Add spacing between commits

    def _display_diff_with_rich(self, diff: str) -> None:
        """Display diff using rich syntax highlighting."""
        syntax = Syntax(diff, "diff", theme="monokai", line_numbers=False, word_wrap=False)
        console.print(Panel(syntax, title="[bold yellow]📄 Diff[/bold yellow]", border_style="yellow"))


def main():
    parser = argparse.ArgumentParser(
        description="Cherry-picking tool for syncing changes between Aurora and Bluefin"
    )
    parser.add_argument(
        "--ours", 
        default="aurora", 
        choices=["aurora", "bluefin"],
        help="Our project name (default: aurora)"
    )
    parser.add_argument(
        "--days", 
        type=int, 
        default=7, 
        help="Number of days to look back (default: 7)"
    )
    parser.add_argument(
        "--no-test",
        action="store_true",
        help="Skip compatibility testing for faster results"
    )
    parser.add_argument(
        "--show-diffs",
        action="store_true",
        help="Show the diff for each commit (can be verbose)"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output for compatibility"
    )
    
    args = parser.parse_args()
    
    # Configure console based on color preference
    if args.no_color:
        console._color_system = None
    
    tool = CherryPickerTool(our_project=args.ours)
    
    try:
        tool.show_status(args.days, test_compatibility=not args.no_test, show_diffs=args.show_diffs)
    except KeyboardInterrupt:
        console.print("\n[red]⏹️ Operation cancelled by user.[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]💥 Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
