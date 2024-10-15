# leader-schedule-monitor
solana leader schedule monitor. wip.

### setup
```
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```
### run
```python3 leader_monitor.py -i <id_pubkey>```

### todo
- show skipped slots

### known issues
- crash during epoch change

![alt text](https://raw.githubusercontent.com/1000xsh/leader-schedule-monitor/main/monitor_output.png)
