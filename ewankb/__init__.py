# Ewan-kb package
__version__ = "0.1.9"


def __getattr__(name):
    """Lazy imports — heavy modules are only loaded when accessed."""
    if name == "KBContext":
        from ewankb.context import KBContext
        return KBContext
    if name == "query":
        from ewankb.query import query
        return query
    if name == "query_graph_json":
        from ewankb.query import query_graph_json
        return query_graph_json
    if name == "query_kb":
        from ewankb.query import query_kb
        return query_kb
    if name == "load_or_build":
        from ewankb.query import load_or_build
        return load_or_build
    raise AttributeError(f"module 'ewankb' has no attribute {name}")


__all__ = ["KBContext", "query", "query_graph_json", "query_kb", "load_or_build"]
