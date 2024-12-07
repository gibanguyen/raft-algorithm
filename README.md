# raft-algorithm
## Installation
```
git clone https://github.com/gibanguyen/raft-algorithm/
```
```
cd raft-algorithm
```
Option 1:
```
pip install -r requirements.txt
```
Option 2: Using virtual environment
```
python -m venv venv 
```
```
source venv/bin/activate
```
```
pip install -r requirements.txt
```

## Run project
```
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. node.proto
```
```
python3 main.py
```
