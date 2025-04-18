# promptbuilder/cli.py

import fnmatch # Import fnmatch for pattern matching
from pathlib import Path
from typing import Optional, List, Set, Dict # Added Set, Dict

import typer
from loguru import logger

# --- Setup logging early ---
from .services.logging import setup_logging
# Logging setup is deferred until callback

# --- Import core components (now decoupled) ---
from .config.loader import get_config
# Import the *core* classes, not the Qt adapters
from .core.fs_scanner import _FileScannerCore
from .core.prompt_engine import PromptEngine
from .core.context_assembler import _ContextAssemblerCore
from .core.models import FileNode
from . import __version__

# Plugins are loaded via __init__

# --- Typer App ---
app = typer.Typer(help="PromptBuilder CLI - Generate prompts headlessly (Windows).")

def version_callback(value: bool):
    if value:
        print(f"PromptBuilder CLI Version: {__version__}")
        raise typer.Exit()

@app.callback()
def main_options(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
    version: Optional[bool] = typer.Option(None, "--version", callback=version_callback, is_eager=True, help="Show version and exit."),
):
    """ Main callback to set up logging """
    log_level = "DEBUG" if verbose else "INFO"
    # Configure logging here, after flags are parsed
    setup_logging(level=log_level, verbose=verbose)
    logger.info(f"Log level set to: {log_level}")
    ctx.ensure_object(dict)
    ctx.obj["VERBOSE"] = verbose


def _filter_nodes(
    nodes: List[FileNode],
    root_path: Path,
    include_patterns: Optional[List[str]],
    exclude_patterns: Optional[List[str]]
) -> List[FileNode]:
    """
    Filters a list of FileNode objects based on include/exclude glob patterns
    applied to paths relative to the root_path.

    Keeps parent directories if any of their children are kept.

    Args:
        nodes: The initial list of FileNode objects (typically top-level items).
        root_path: The absolute root path used for relative calculations.
        include_patterns: List of glob patterns to include. If None or empty, all nodes are initially considered.
        exclude_patterns: List of glob patterns to exclude after includes.

    Returns:
        A flat list containing *only* the FileNode objects (both files and directories)
        that were ultimately kept after applying include and exclude rules.
        The hierarchical structure is *not* rebuilt in the returned list.
    """
    if not include_patterns and not exclude_patterns:
        return nodes # No filtering needed

    kept_paths: Set[Path] = set() # Store paths of nodes that should be kept

    # --- Inclusion Pass ---
    nodes_to_consider = nodes
    if include_patterns:
        logger.debug(f"Applying include patterns: {include_patterns}")
        included_paths_pass1: Set[Path] = set()
        # Use a stack for iterative traversal of the initial node list and their children
        stack: List[FileNode] = list(nodes_to_consider)
        processed_for_include: Set[Path] = set() # Avoid reprocessing nodes

        while stack:
            node = stack.pop()
            if node.path in processed_for_include: continue
            processed_for_include.add(node.path)

            try:
                relative_path = node.path.relative_to(root_path).as_posix()
            except ValueError:
                relative_path = node.name # Fallback

            is_match = False
            for pattern in include_patterns:
                if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(node.name, pattern):
                    is_match = True
                    break

            if is_match:
                # If a node matches, keep it and ensure all its parents are also marked
                curr = node
                while curr is not None:
                    if curr.path in included_paths_pass1: break # Already marked up this branch
                    included_paths_pass1.add(curr.path)
                    curr = curr.parent
            # Always traverse children, regardless of parent match status,
            # as a child might match an include pattern even if the parent doesn't.
            if node.is_dir:
                stack.extend(node.children) # Add children to the stack

        kept_paths = included_paths_pass1
        logger.info(f"Include pass identified {len(kept_paths)} potential paths.")
    else:
        # No include patterns: initially consider all paths from the input nodes and their descendants
        stack = list(nodes)
        all_paths: Set[Path] = set()
        processed_all: Set[Path] = set()
        while stack:
             node = stack.pop()
             if node.path in processed_all: continue
             processed_all.add(node.path)
             all_paths.add(node.path)
             if node.is_dir: stack.extend(node.children)
        kept_paths = all_paths
        logger.info("No include patterns, considering all scanned paths initially.")


    # --- Exclusion Pass ---
    if exclude_patterns:
        logger.debug(f"Applying exclude patterns: {exclude_patterns}")
        paths_to_exclude: Set[Path] = set()
        # Check all potentially kept paths against exclusion rules
        # Iterate through all original nodes again to check patterns
        stack = list(nodes)
        processed_for_exclude: Set[Path] = set()

        while stack:
             node = stack.pop()
             if node.path in processed_for_exclude: continue
             processed_for_exclude.add(node.path)

             # Only check nodes that were potentially kept by the include pass
             if node.path not in kept_paths:
                  if node.is_dir: stack.extend(node.children) # Still need to check children
                  continue

             try:
                relative_path = node.path.relative_to(root_path).as_posix()
             except ValueError:
                relative_path = node.name

             is_excluded = False
             for pattern in exclude_patterns:
                 if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(node.name, pattern):
                     is_excluded = True
                     break

             if is_excluded:
                 # If a node is excluded, mark it and all its descendants for removal
                 exclusion_stack = [node]
                 processed_exclusion_stack: Set[Path] = set()
                 while exclusion_stack:
                      ex_node = exclusion_stack.pop()
                      if ex_node.path in processed_exclusion_stack: continue
                      processed_exclusion_stack.add(ex_node.path)

                      paths_to_exclude.add(ex_node.path)
                      if ex_node.is_dir: exclusion_stack.extend(ex_node.children)
             elif node.is_dir: # If directory not excluded, check its children
                  stack.extend(node.children)

        # Remove excluded paths
        final_kept_paths = kept_paths - paths_to_exclude
        logger.info(f"Exclude pass removed {len(paths_to_exclude)} paths. Keeping {len(final_kept_paths)}.")
        kept_paths = final_kept_paths


    # --- Collect the actual FileNode objects corresponding to kept paths ---
    # Fixes regression #2: Clarify that this returns a flat list.
    # The reconstruction of the tree is complex and not needed by the current caller.
    filtered_nodes_flat: List[FileNode] = []
    stack = list(nodes)
    processed_final: Set[Path] = set()
    while stack:
         node = stack.pop()
         if node.path in processed_final: continue
         processed_final.add(node.path)

         if node.path in kept_paths:
              # Add the node itself to the flat list if its path was kept
              filtered_nodes_flat.append(node)

         # Always traverse children, as a child might be kept even if parent wasn't initially added
         # (e.g., parent excluded, but child included by a more specific rule - though current logic might not handle this perfectly)
         if node.is_dir: stack.extend(node.children)

    logger.debug(f"Filter function returning flat list of {len(filtered_nodes_flat)} kept nodes.")
    return filtered_nodes_flat


def _collect_paths_from_nodes(nodes: List[FileNode]) -> Set[Path]:
    """
    Helper to recursively extract all *file* paths from a flat list of FileNode objects.
    It traverses directories found in the list to find nested files.
    """
    paths: Set[Path] = set()
    # Use a stack and track visited directories to handle potential duplicates if
    # the input list contains both a directory and its children.
    stack = list(nodes)
    visited_nodes : Set[Path] = set()

    while stack:
        node = stack.pop()
        if node.path in visited_nodes: continue
        visited_nodes.add(node.path)

        if not node.is_dir:
            paths.add(node.path)
        else:
             # If it's a directory, add its direct children to the stack to process them.
             # This ensures we find files within directories present in the input list.
             stack.extend(node.children)
    return paths


@app.command()
def build(
    repo: Path = typer.Option(..., "--repo", "-r", help="Path to the repository root.", exists=True, file_okay=False, dir_okay=True, readable=True, resolve_path=True),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Glob patterns for files/folders to include (relative to repo root, e.g., 'src/**/*.py', '*.md')."),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Glob patterns for files/folders to exclude (applied after includes, e.g., '**/test_*', 'docs/')."),
    output: Path = typer.Option("prompt.xml", "--output", "-o", help="Output file path for the generated prompt.", writable=True, resolve_path=True),
    # Snippet selection (same as before)
    objective: Optional[List[str]] = typer.Option(None, "--objective", help="Objective snippet name(s) (e.g., 'Review', 'Develop'). Use 'Custom' for custom text."),
    objective_custom: Optional[str] = typer.Option(None, "--objective-custom", help="Custom text if '--objective Custom' is used."),
    scope: Optional[List[str]] = typer.Option(None, "--scope", help="Scope snippet name(s)."),
    scope_custom: Optional[str] = typer.Option(None, "--scope-custom", help="Custom text if '--scope Custom' is used."),
    requirements: Optional[List[str]] = typer.Option(None, "--requirements", help="Requirements snippet name(s)."),
    requirements_custom: Optional[str] = typer.Option(None, "--requirements-custom", help="Custom text if '--requirements Custom' is used."),
    constraints: Optional[List[str]] = typer.Option(None, "--constraints", help="Constraints snippet name(s)."),
    constraints_custom: Optional[str] = typer.Option(None, "--constraints-custom", help="Custom text if '--constraints Custom' is used."),
    process: Optional[List[str]] = typer.Option(None, "--process", help="Process snippet name(s)."),
    process_custom: Optional[str] = typer.Option(None, "--process-custom", help="Custom text if '--process Custom' is used."),
    output_format: Optional[List[str]] = typer.Option(None, "--output-format", help="Output format snippet name(s)."),
    output_format_custom: Optional[str] = typer.Option(None, "--output-format-custom", help="Custom text if '--output-format Custom' is used."),
    question: Optional[List[str]] = typer.Option(None, "--question", help="Additional question(s) to include (full text)."),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Override maximum context tokens."),
):
    """
    Builds a prompt by scanning a repository and selecting snippets via CLI flags.
    """
    logger.info(f"Building prompt for repository: {repo}")
    logger.info(f"Output will be saved to: {output}")

    config = get_config() # Load config to get ignore patterns, snippet defs
    engine = PromptEngine() # Uses loaded config

    # --- Scan Repository (using sync core scanner) ---
    logger.info("Scanning repository...")
    # Pass repo path to the scanner core instance
    scanner = _FileScannerCore(root_path=repo, ignore_patterns=config.ignore_patterns)
    try:
        # Run the synchronous scan
        root_nodes = scanner.scan_directory_sync()
        if not root_nodes:
             logger.error("Scan returned no files or directories. Check path and permissions.")
             raise typer.Exit(code=1)
        # We expect only one root node from the scan
        scanned_nodes = root_nodes[0].children # Get children of the root repo node
    except ValueError as e:
         logger.error(f"Scan Error: {e}")
         raise typer.Exit(code=1)
    except Exception as e:
        logger.exception(f"Unexpected error during repository scan: {e}")
        raise typer.Exit(code=1)

    logger.info(f"Scan complete. Found {len(scanned_nodes)} top-level items initially.")

    # --- Filter scanned nodes based on include/exclude patterns ---
    selected_nodes_flat = _filter_nodes(scanned_nodes, repo, include, exclude)

    # --- Extract file paths from selected nodes ---
    # Pass the flat list of kept nodes (including directories) to collect leaf files
    selected_paths = _collect_paths_from_nodes(selected_nodes_flat)

    if not selected_paths:
         logger.error("No files selected after applying include/exclude patterns. Aborting.")
         raise typer.Exit(code=1)
    logger.info(f"Selected {len(selected_paths)} files for context.")


    # --- Determine selected snippets (logic remains the same) ---
    selected_snippets_cli: Dict[str, Dict[str, Optional[str]]] = {}
    snippet_map = { # Map CLI flags to config keys and custom text args
        "objective": ("Objective", objective_custom),
        "scope": ("Scope", scope_custom),
        "requirements": ("Requirements", requirements_custom),
        "constraints": ("Constraints", constraints_custom),
        "process": ("Process", process_custom),
        "output_format": ("Output", output_format_custom), # Map CLI flag to config key
    }
    cli_args = locals() # Get local variables dict

    for flag_name, (config_key, custom_text_arg) in snippet_map.items():
        selected_names = cli_args.get(flag_name)
        if selected_names:
            category_data = config.prompt_snippets.get(config_key)
            if category_data is None:
                 logger.warning(f"Snippet category '{config_key}' not found in configuration. Skipping flag '--{flag_name}'.")
                 continue
            category_items = category_data.items

            valid_selections: Dict[str, Optional[str]] = {}
            for name in selected_names:
                if name == "Custom":
                    custom_text = cli_args.get(custom_text_arg)
                    if custom_text: valid_selections["Custom"] = custom_text
                    else: logger.warning(f"'--{flag_name} Custom' used but '--{flag_name}-custom' not provided. Ignoring Custom.")
                elif name in category_items: valid_selections[name] = None
                else: logger.warning(f"Invalid snippet name '{name}' for category '{config_key}'. Ignoring.")
            if valid_selections: selected_snippets_cli[config_key] = valid_selections

    selected_questions_cli: Set[str] = set()
    if question:
        valid_questions = {q for q in question if q in config.common_questions}
        invalid_questions = set(question) - valid_questions
        if invalid_questions: logger.warning(f"Ignoring invalid questions: {invalid_questions}")
        selected_questions_cli.update(valid_questions)

    # --- Build Instructions ---
    logger.debug(f"Selected Snippets: {selected_snippets_cli}")
    logger.debug(f"Selected Questions: {selected_questions_cli}")
    instructions_xml = engine.build_instructions_xml(selected_snippets_cli, selected_questions_cli)

    # --- Assemble Context (using sync core assembler) ---
    logger.info("Assembling context...")
    context_max_tokens = max_tokens if max_tokens is not None else config.max_context_tokens
    assembler = _ContextAssemblerCore(secret_patterns=config.secret_patterns)
    try:
        context_result = assembler.assemble_context_sync(selected_paths, context_max_tokens)
    except Exception as e:
        logger.exception(f"Error assembling context: {e}")
        raise typer.Exit(code=1)

    # --- Combine and Save ---
    final_prompt = instructions_xml + "\n\n" + context_result.context_xml
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(final_prompt, encoding='utf-8')
        logger.success(f"Prompt successfully written to: {output}")
        logger.info(f"Final Token Count: {context_result.total_tokens}/{context_max_tokens}")
        if context_result.budget_details: logger.info(f"Context Budget Note: {context_result.budget_details}")
        if context_result.skipped_files: logger.warning(f"Skipped {len(context_result.skipped_files)} files due to budget or errors.")

    except Exception as e:
        logger.exception(f"Error writing output file: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()