# nexus_traffic_monitor (NTM)
Monitor Cisco Nexus 9000 Switches

# Use Cases
Originally developed for RoCEv2 traffic monitoring on Cisco Nexus 9000 Switches.

Switch health
<img width="1710" alt="image" src="https://github.com/user-attachments/assets/3896e2ee-861e-4f6d-b222-66a3c2637371">

Interface inventory
<img width="1711" alt="image" src="https://github.com/user-attachments/assets/0428466a-02e4-4998-bec8-34a248c08b15">

Interface states, modes, peer types, etc. in the entire install base including many fabrics and DCs.
<img width="1709" alt="image" src="https://github.com/user-attachments/assets/be047536-2b55-4b0d-9f03-f2e48d45fcce">

Switches acorss many fabrics and DCs.
<img width="1705" alt="image" src="https://github.com/user-attachments/assets/b8ac5e63-3c4d-4ed5-8bd4-efb07d5ecfe1">

Interfaces acorss many fabrics and DCs.
<img width="1705" alt="image" src="https://github.com/user-attachments/assets/61d2a86a-83c1-4bc3-8b7a-ba61f30a224c">

Top utilized switch interfaces for % and absolute (Gbps). These are the hot spots to drill-down.
<img width="1703" alt="image" src="https://github.com/user-attachments/assets/641f83b9-7619-4422-a286-d6033a9cbfc0">

Errors like CRC, Stomped CRC
<img width="1710" alt="image" src="https://github.com/user-attachments/assets/3651aaba-baf8-469d-af34-3f09be6246c6">

Drops and Random Drops from switch interface queues
<img width="1708" alt="image" src="https://github.com/user-attachments/assets/26b2a54f-77da-4f33-99a6-846fc971a9e2">

Pause frame monitoring to detect congestion in lossless Ethernet networks used for RoCEv2 traffic
<img width="1706" alt="image" src="https://github.com/user-attachments/assets/d8e833aa-bb69-46a6-aa37-a2552cdaf075">

ECN counters used by TCP as well as RoCEv2 Congestion Management (RCM)
<img width="1707" alt="image" src="https://github.com/user-attachments/assets/ddadeca3-bfd5-44fb-956b-17d2c9a7c4e2">

Time-series views to detect the exact timne of spikes and dips
<img width="1708" alt="image" src="https://github.com/user-attachments/assets/b24b989e-8c3b-49b1-9a7e-ae4c70897d53">
<img width="1709" alt="image" src="https://github.com/user-attachments/assets/080b4bef-ac33-46b4-a8b9-a5845ff89466">
<img width="1710" alt="image" src="https://github.com/user-attachments/assets/8bb8610a-d291-4ffb-b740-866f23fd8967">

Switch buffer peak usage
<img width="1716" alt="image" src="https://github.com/user-attachments/assets/c1860315-21a6-422e-b1d0-602f4d454998">

Detailed interface absolute and % utilization at 20-second and (optional) 1-second granularity
<img width="1709" alt="image" src="https://github.com/user-attachments/assets/abea9fc9-a5c5-4a0a-8da6-14b930c5ac19">

Detailed packet-size distribution, drops, and errors
<img width="1707" alt="image" src="https://github.com/user-attachments/assets/6735fe69-2cd7-4d17-9f28-2186e3fb43ab">

Queue depth monitoring
<img width="1711" alt="image" src="https://github.com/user-attachments/assets/6bcda045-de49-4df3-ba8f-ce2d4e1320cf">

Burst detection
<img width="1708" alt="image" src="https://github.com/user-attachments/assets/4b139166-1ddc-41fc-ae0e-be55881e8ec5">

Pause frames compared againts traffic in the reverse directions - Used for lossless Ethernet while transporting RoCEv2 traffic
<img width="1714" alt="image" src="https://github.com/user-attachments/assets/2623f91c-bb66-47a2-9eef-b9208d9fc1f4">

## Architecture
The NTM collector (nexus_traffic_monitor_*.py) pulls stats from Cisco Nexus 9000 switches using NX-API (HTTP) and SSH. The stats are normalized and correlated before writing to InfluxDB. Finally, Grafana provides the visualization and use-cases.

- **Data source**: [Cisco Nexus 9000 Switches)]([https://developer.cisco.com/docs/mds-9000-nx-api-reference/](https://github.com/paregupt/nexus_traffic_monitor/blob/main/telegraf/nexus_traffic_monitor_high_frequency.py)), read-only account is enough
- **Data storage**: [InfluxDB](https://github.com/influxdata/influxdb), a time-series database
- **Visualization**: [Grafana](https://github.com/grafana/grafana)

## Installation
- Tested OS: Ubuntu 22.04. Should work on other OS also.
- Python version: Version 3 only.
- Tested Nexus Switches: Nexus 9332D-GX2B and 9364D-GX2A running 10.(4).x and 10.(5).x.

Start with a Ubuntu machine with 8 GB memory, 4 or 8 CPUs, 100 GB disk. Add more if planning to monitor many switches or you can add the resources later after starting fresh. My Ubuntu VM has 32 GB memory (usage remains under 16 GB), 16 CPUs, 1 TB disk monitoring 20 switches with 1800 interfaces. Monitoring and RnD for six months increased disk usage by 400 GB. I recommend SSD for faster write and read performance, especially for 1-second granular data and faster loading of the Grafana panels over longer duration.

## InfluxbDB
This project uses InfluxDB 1.8.10 or the latest 1.x. No Influx 2.0. No Influx 3.0 yet.
```
wget https://download.influxdata.com/influxdb/releases/influxdb_1.8.10_amd64.deb
sudo dpkg -i influxdb_1.8.10_amd64.deb
```
## Grafana
Used Grafana versions: 10.x and 11.2

```
sudo apt-get install -y adduser libfontconfig1 musl
wget https://dl.grafana.com/oss/release/grafana_11.2.2_amd64.deb
sudo dpkg -i grafana_11.2.2_amd64.deb
```
## Telegraf
Used version: 1.29.5. But any other telegraf version should work.

### Install Telegraf
```
wget https://dl.influxdata.com/telegraf/releases/telegraf_1.29.5-1_amd64.deb 
sudo dpkg -i telegraf_1.29.5-1_amd64.deb
```

### Setup Telegraf
Telegraf by default runs as a service by the telegraf user. But I prefer running telegraf under a different user with access to sudo commands. So edit /lib/systemd/system/telegraf.service and change User=telegraf to something else, for example User=paresh.

To allow running sudo command by the user, paresh, without asking for password, I add a new file, name 91-paresh at /etc/sudoers.d/ with the following line:
```
ciscouser ALL=(ALL) NOPASSWD:ALL
```
Change this content to allow only specific sudo commands.

Change ownership of /var/log/telegraf to ciscouser to allow this user to write logs
```
sudo chown -R paresh:sudo /var/log/telegraf
```

Restart telegraf service
```
sudo systemctl daemon-reload
sudo systemctl start telegraf
```
### Configure Telegraf for NTM collection
This is the high-level design. The exec input plugin in Telegraf runs the NTM collector (nexus_traffic_monitor_high_frequency.py) every 20-seconds or similar interval. The NTM collector reads the switch credentials from an input file, pulls metrics from the switchec, cleans them, correlates them, and prints the output in InfluxDB Line Protocol format. Telegraf uses this output to write the metrics to InfluxDB. 

Following are the steps.
Create /usr/local/telegraf directory and copy the NTM collector, nexus_traffic_monitor_high_frequency.py, and switch1.txt file inside it.
```
cd
git clone https://github.com/paregupt/nexus_traffic_monitor.git
sudo mkdir /usr/local/telegraf
sudo chown paresh:sudo /usr/local/telegraf
cp nexus_traffic_monitor/telegraf/* /usr/local/telegraf/
```

Run NTM collector to learn about its options
```
python3 /usr/local/telegraf/nexus_traffic_monitor_high_frequency.py -h
```

Edit the switch1.txt file to add switch credentials. [Read more details here](https://github.com/paregupt/nexus_traffic_monitor/blob/main/telegraf/switch1.txt).
You should also change the filename to a more meaningful name, such as the switchname. The NTM collector requires one such input file per switch. For 100 switches, there would be 100 such files. So name them accordingly.

Edit /etc/telegraf/telegraf.conf with the following:

```
[agent]
  precision = "1ms"
  logfile = "/var/log/telegraf/telegraf.log"
  logfile_rotation_max_size = "10MB"
  logfile_rotation_max_archives = 5

[[inputs.exec]]
   interval = "20000ms"
   commands = [
       "python3 /usr/local/telegraf/nexus_traffic_monitor_high_frequency.py /usr/local/telegraf/nexus_cisco-sw.txt influxdb-lp -vv",
   ]
   timeout = "19000ms"
   data_format = "influx"

[[inputs.exec]]
   interval = "20000ms"
   commands = [
       "python3 /usr/local/telegraf/nexus_traffic_monitor_high_frequency.py /usr/local/telegraf/nexus_N9364C-H1-1.txt influxdb-lp -vv --utcoh 7",
   ]
   timeout = "19000ms"
   data_format = "influx"

 [[outputs.influxdb]]





### DIY Installation
1. Install Telegraf
1. Install InfluxDB
1. Install Grafana
1. Download this repo in zip format or via git clone.
