# promptbuilder/core/models.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Set

@dataclass
class FileNode:
    """Represents a file or directory in the scanned tree."""
    path: Path
    name: str
    is_dir: bool
    size: int = 0 # Size in bytes, 0 for directories
    mod_time: float = 0.0 # Modification time (timestamp)
    children: List['FileNode'] = field(default_factory=list)
    parent: Optional['FileNode'] = None # Optional link back to parent
    # Add state for UI if needed (e.g., checked status), though better in ViewModel
    # checked: bool = False

    # Allow hashing based on path for use in sets
    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        if not isinstance(other, FileNode):
            return NotImplemented
        return self.path == other.path

@dataclass
class PromptSnippet:
    """Represents a selected instruction snippet."""
    category: str
    name: str # e.g., "Concept", "High-level", "Custom"
    text: str # The actual text of the snippet

@dataclass
class ContextFile:
    """Represents a file included in the context."""
    path: Path
    content: str
    tokens: int
    status: str = "included" # e.g., included, truncated, skipped_size, skipped_secret

@dataclass
class ContextResult:
    """Result of the context assembly process."""
    context_xml: str
    included_files: List[ContextFile]
    skipped_files: List[ContextFile] # Files skipped due to budget or other reasons
    total_tokens: int
    budget_details: str # Message about truncation/skipping

@dataclass
class ProjectState:
    """Represents the state of a single project tab."""
    id: str # Unique ID for the tab/project
    config: 'TabConfig' # Reference to the config for this tab
    root_node: Optional[FileNode] = None # Root of the scanned file tree
    selected_files: Set[Path] = field(default_factory=set) # Paths of selected files/dirs
    selected_snippets: Dict[str, Dict[str, Optional[str]]] = field(default_factory=dict) # {Category: {Name: CustomText}}
    selected_questions: Set[str] = field(default_factory=set)
    # Add other state like filter text, sort mode, expansion state etc.