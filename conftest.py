# conftest.py
# Prevent pytest from adding mcp_servers/* subdirectories to sys.path
# automatically, which would cause "server" module name collisions when
# multiple test files import different server.py files.
collect_ignore_glob = []
