from db import execute
execute("UPDATE storage_nodes SET node_url='http://100.82.80.92:7002' WHERE node_name='pc-2-node'")
print("updated")