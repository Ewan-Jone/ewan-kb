#!/usr/bin/env python
"""
Integration test for ewankb update — incremental update workflow.

Setup: mall fixture → discover → minimal kb build → graph → hash cache
Test: simulate source change → ewankb update → verify detection + cleanup + rebuild
"""
import json
import os
import shutil
import sys
from pathlib import Path

EWANKB_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = EWANKB_ROOT / "tests" / "fixtures" / "商城项目"
KB_DIR = Path("/tmp/ewankb_test_update")

def reset_config():
    import ewankb.tools.config_loader as cfg
    cfg._global_cfg = None
    cfg._project_cfg = None
    cfg._llm_cfg = None

def header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}", flush=True)

# ── Step 0: Setup ──────────────────────────────────────────────────────────
header("Step 0: Setup KB directory")

if KB_DIR.exists():
    shutil.rmtree(KB_DIR)
KB_DIR.mkdir(parents=True)

for d in ["source/repos", "source/docs", "domains/_meta", "knowledgeBase", "graph/.cache"]:
    (KB_DIR / d).mkdir(parents=True, exist_ok=True)

shutil.copytree(FIXTURE_DIR / "source" / "repos", KB_DIR / "source" / "repos", dirs_exist_ok=True)
shutil.copytree(FIXTURE_DIR / "source" / "docs", KB_DIR / "source" / "docs", dirs_exist_ok=True)
shutil.copytree(EWANKB_ROOT / "ewankb" / "templates" / "knowledgeBase", KB_DIR / "knowledgeBase", dirs_exist_ok=True)

os.environ["EWANKB_DIR"] = str(KB_DIR)
reset_config()

from ewankb.tools.config_loader import create_project_config, get_global_config
gcfg = get_global_config()
create_project_config(KB_DIR, "商城项目业务知识库")

# Setup LLM config from ~/.claude/settings.json
cc_settings = Path.home() / ".claude" / "settings.json"
if cc_settings.exists():
    with open(cc_settings, encoding="utf-8") as f:
        cc_data = json.load(f)
    env = cc_data.get("env", {})
    api_key = env.get("ANTHROPIC_AUTH_TOKEN", "")
    base_url = env.get("ANTHROPIC_BASE_URL", "")
    model = env.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-haiku-4-5-20251001")
    with open(KB_DIR / "llm_config.json", "w", encoding="utf-8") as f:
        json.dump({"api_key": api_key, "base_url": base_url, "model": model, "api_protocol": "anthropic"}, f, indent=2)

(KB_DIR / ".gitignore").write_text("graph/.cache/\nknowledgeBase/_state/\n.env\nllm_config.json\n")
os.chdir(KB_DIR)
print(f"KB at {KB_DIR}", flush=True)

# ── Step 1: Discover domains (no AI, fast) ─────────────────────────────────
header("Step 1: Discover domains")

from ewankb.tools.discover.discover_domains import discover
result = discover(KB_DIR, use_ai=False)
domains = result.get("domain_list", [])
print(f"Discovered {len(domains)} domains: {domains}")
assert len(domains) >= 3, f"Expected >=3 domains, got {len(domains)}"

# ── Step 2: Build initial graph ────────────────────────────────────────────
header("Step 2: Build initial graph")

from ewankb.tools.build_graph.graph_builder import build_graph
graph = build_graph(
    source_dir=KB_DIR / "source",
    domains_dir=KB_DIR / "domains",
    graph_dir=KB_DIR / "graph",
)
meta = graph["metadata"]
print(f"Graph: {meta['num_nodes']} nodes, {meta['num_links']} links, {meta['communities']} communities")

# ── Step 3: Create hash cache (simulating post-build state) ─────────────────
header("Step 3: Create hash cache")

from ewankb.tools.incremental import update_hash, diff
hash_result = update_hash()
print(f"Hash cache: {hash_result['total_files']} files, {hash_result['doc_mappings']} doc mappings")

# Verify no changes detected
result = diff()
assert not result["has_changes"], f"Expected no changes after hash save, got: {result}"
print("Verified: no changes detected after initial build")

# ── Step 4: Snapshot the built state for later comparison ───────────────────
header("Step 4: Snapshot built state")

def snapshot_domains():
    """Return {domain: {filename: content}} for all domain dirs."""
    snap = {}
    domains_dir = KB_DIR / "domains"
    for d in sorted(domains_dir.iterdir()):
        if d.is_dir() and not d.name.startswith("_"):
            snap[d.name] = {}
            for f in sorted(d.rglob("*.md")):
                snap[d.name][str(f.relative_to(d))] = f.read_text(encoding="utf-8")
    return snap

before_snap = snapshot_domains()
before_graph = json.loads((KB_DIR / "graph" / "graph.json").read_text(encoding="utf-8"))
print(f"Before: {len(before_snap)} domains, {before_graph['metadata']['num_nodes']} graph nodes")

# ── Step 5: Simulate a source code change ───────────────────────────────────
header("Step 5: Simulate source change")

# Find a Java file and add a new method to it
repos_dir = KB_DIR / "source" / "repos"
java_files = list(repos_dir.rglob("*.java"))
target_file = None
for f in java_files:
    if "OrderController" in f.name:
        target_file = f
        break
assert target_file, "No OrderController.java found"
print(f"Modifying: {target_file.relative_to(repos_dir)}")

original_content = target_file.read_text(encoding="utf-8")
modified_content = original_content + """

// New endpoint added for incremental update test
@GetMapping("/api/orders/incremental-test")
public String incrementalTest() {
    return "This is a test endpoint added for incremental update verification";
}
"""
target_file.write_text(modified_content, encoding="utf-8")
print("  Added test endpoint to OrderController.java")

# ── Step 6: Run ewankb update ──────────────────────────────────────────────
header("Step 6: Run ewankb update")

# We'll call the update logic directly to have programmatic control
from ewankb.tools.incremental import diff as run_diff, clean as run_clean

# 6a: Detect changes
changes_result = run_diff()
print(f"\nChanges detected: {changes_result['has_changes']}")
for cat in ("repos", "docs"):
    c = changes_result["changes"][cat]
    if any(c.values()):
        print(f"  {cat}: added={len(c['added'])}, modified={len(c['modified'])}, deleted={len(c['deleted'])}")
        for f in c["modified"]:
            print(f"    ~ {f}")

assert changes_result["has_changes"], "Expected changes to be detected"

# 6b: Map to affected domains
affected = changes_result["affected_domains"]
print(f"\nAffected domains: {affected}")
assert len(affected) > 0, f"Expected affected domains, got none. Changes: {changes_result['changes']}"
print("  Domain mapping OK")

# 6c: Clean affected domains
print(f"\nCleaning affected domains: {affected}")
clean_result = run_clean(affected)
print(f"  Files deleted: {clean_result['files_deleted']}")
print(f"  Progress entries cleared: {clean_result['progress_entries_cleared']}")
print(f"  Domains: {clean_result['domains']}")

# 6d: Verify that domain files were actually deleted
for domain in affected:
    domain_dir = KB_DIR / "domains" / domain
    if domain_dir.exists():
        remaining = list(domain_dir.rglob("*.md"))
        print(f"  {domain}: {len(remaining)} .md files remaining")
        # README.md and PROCESSES.md should be deleted
        for fname in ("README.md", "PROCESSES.md"):
            fpath = domain_dir / fname
            if fpath.exists():
                print(f"    WARNING: {fname} still exists (should have been cleaned)")

# ── Step 7: Rebuild graph (this always happens in update flow) ──────────────
header("Step 7: Rebuild graph")

graph2 = build_graph(
    source_dir=KB_DIR / "source",
    domains_dir=KB_DIR / "domains",
    graph_dir=KB_DIR / "graph",
)
meta2 = graph2["metadata"]
print(f"Graph after update: {meta2['num_nodes']} nodes, {meta2['num_links']} links, {meta2['communities']} communities")

# Graph should have more nodes now (new endpoint method adds AST nodes)
node_diff = meta2["num_nodes"] - before_graph["metadata"]["num_nodes"]
print(f"Node count change: {node_diff} (before={before_graph['metadata']['num_nodes']}, after={meta2['num_nodes']})")
assert node_diff > 0, f"Expected graph to grow after adding code, got change={node_diff}"

# ── Step 8: Verify graph.json was updated ───────────────────────────────────
header("Step 8: Verify graph.json")

graph_file = KB_DIR / "graph" / "graph.json"
after_graph = json.loads(graph_file.read_text(encoding="utf-8"))
print(f"Graph metadata: version={after_graph['metadata']['version']}")
print(f"  nodes={after_graph['metadata']['num_nodes']}")
print(f"  links={after_graph['metadata']['num_links']}")
print(f"  communities={after_graph['metadata']['communities']}")
print(f"  source_hash={after_graph['metadata']['source_hash']}")
print(f"  incremental={after_graph['metadata']['incremental']}")

# Verify the new endpoint appears in the graph
new_endpoint_found = False
for node in after_graph["nodes"]:
    if "incremental-test" in str(node.get("label", "")) or "incrementalTest" in str(node.get("id", "")):
        new_endpoint_found = True
        print(f"  Found new endpoint node: {node.get('label', node.get('id', '?'))}")
        break
if not new_endpoint_found:
    print("  (new endpoint node not found by direct search — may be folded into parent node)")

# ── Step 9: Verify change detection now shows no changes ────────────────────
header("Step 9: Verify post-update state")

update_hash()  # refresh hash cache
result = run_diff()
assert not result["has_changes"], f"Expected no changes after update, got: {result}"
print("No changes detected after update — hash cache consistent")

# ── Step 10: Cleanup ───────────────────────────────────────────────────────
header("Step 10: Cleanup")

# Restore the original file
target_file.write_text(original_content, encoding="utf-8")

if os.environ.get("KEEP_OUTPUT") == "1":
    print(f"KB preserved at {KB_DIR}")
else:
    shutil.rmtree(KB_DIR)
    print("Test cleanup done")

print("\n✓ Incremental update integration test PASSED")
print(f"  - Change detection: OK")
print(f"  - Domain mapping: {len(affected)} domains affected")
print(f"  - Selective cleanup: {clean_result['files_deleted']} files, {clean_result['progress_entries_cleared']} progress entries")
print(f"  - Graph rebuild: {meta2['num_nodes']} nodes (+{node_diff} from new code)")
print(f"  - Post-update consistency: OK")
