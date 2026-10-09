# Walkthrough

How to open the lab, get into the devices, and how each part is built, in the order you would
build it by hand. Every step has the commands, what they do, and a `show` command to prove it
worked. The examples are the real ones from this network.

## Part A - opening and getting around

1. Open Packet Tracer, File > Open, pick `RHS School Network.pkt`.
2. Wait about a minute. Link lights start orange and turn green when spanning tree is done.
3. The text on the canvas says what the lab does and what each layer is. Each layer and each
   room has its own coloured box. Zoom with Ctrl/Cmd + scroll. The same text is under the **i**
   button (top left of the workspace).
4. Bottom right: **Realtime** is normal. **Simulation** lets you watch one packet hop by hop
   (very good for seeing where an ACL drops something).

### Getting into a router or switch

1. Click the device, then the **CLI** tab, press Enter.
2. Log in: `admin` / `RHSadmin`.
3. The prompt tells you where you are:

       SW-E230>            user mode, can only look at a few things
       SW-E230#            privileged mode (type: enable, password RHSenable)
       SW-E230(config)#    global config (type: configure terminal)
       SW-E230(config-if)# inside one interface (type: interface fa0/1)

4. `exit` goes back one level, `end` goes straight back to `#`.
5. `?` shows what you can type next. Tab finishes a word. `sh ip int br` is the short way of
   typing `show ip interface brief`.
6. `show running-config` is the config in use now. `copy running-config startup-config` saves
   it so it survives a reload. Then File > Save to keep it in the .pkt.

### Getting into a PC or server

Click it, **Desktop** tab:

- **IP Configuration** - DHCP or static address
- **Command Prompt** - `ipconfig`, `ping`, `tracert`, `ssh -l admin 10.10.99.11`, `ftp 10.10.70.30`
- **Web Browser** - type `www.rhs.lab`

On a server the **Services** tab has DHCP, DNS, HTTP, Syslog, NTP, FTP.

### SSH the way IT would do it

Keys cannot be stored in the file, so once on each device:

    SW-E230(config)# crypto key generate rsa
    How many bits in the modulus [512]: 1024

Then from IT-PC1 > Command Prompt: `ssh -l admin 10.10.99.11`. Try the same from a student PC.
It gets refused, because of `access-class 10 in` on the vty lines.

### Screenshots

Mac: Cmd + Shift + 4, then Space, then click the Packet Tracer window. The file lands on the
Desktop (or the Screenshots folder). Rename it to the name from the list in README section 11
and move it into the `screenshots` folder.

## Part B - building it step by step

To practise, open a new empty Packet Tracer file and build one room first (one 2960, a few
PCs, one 3650). Check each step before the next one. That is the main thing I learned:
if you type everything and test at the end, you do not know which part is broken.

### Step 1 - basic setup of every device

    enable
    configure terminal
    hostname SW-E230
    no ip domain-lookup
    service password-encryption
    enable secret RHSenable
    username admin privilege 15 secret RHSadmin
    banner motd #Authorized users only#
    line con 0
     login local
     logging synchronous

- `no ip domain-lookup` stops the switch freezing for 30 seconds when you mistype a command
- `enable secret` is stored as a hash. `enable password` is not, so do not use it
- `login local` means "ask for a username from the local list"

Check: `exit` all the way out and log in again.

### Step 2 - VLANs and access ports (access switch)

    vlan 10
     name STUDENTS
    vlan 20
     name TEACHERS
    vlan 99
     name NETWORK-IT
    interface range fa0/1 - 15
     switchport mode access
     switchport access vlan 10
    interface fa0/16
     switchport mode access
     switchport access vlan 20

A VLAN is a separate layer 2 network inside the same switch. A port in VLAN 10 can only talk
to other VLAN 10 ports until a router connects the VLANs.

Check: `show vlan brief`. Two student PCs with static addresses in the same subnet can ping.
A student PC and the teacher PC cannot, even in the same subnet.

### Step 3 - trunks (access switch to distribution)

    interface gi0/1
     switchport mode trunk
     switchport trunk native vlan 999
     switchport trunk allowed vlan 10,20,99
     switchport nonegotiate

A trunk carries several VLANs on one cable by adding a tag (802.1Q) to each frame. Do the same
on the other end of the cable. On a 3650 you may need `switchport trunk encapsulation dot1q`
first if it complains.

- `allowed vlan` - only these VLANs cross. If you add a VLAN later use
  `switchport trunk allowed vlan add 30`, or you wipe the list
- native VLAN must match on both ends or you get a mismatch message

Check: `show interfaces trunk` on both ends. This is the first place to look when a VLAN
"does not work" on another switch.

### Step 4 - gateways with SVIs (distribution switch)

    ip routing
    vlan 10
     name STUDENTS
    interface vlan 10
     ip address 10.10.8.2 255.255.252.0
     no shutdown

`ip routing` turns a layer 3 switch into a router. An SVI (`interface vlan 10`) is the
switch's own leg in that VLAN, and it becomes the PCs' default gateway. The VLAN has to exist
on the switch and be up on at least one port, or the SVI stays down.

Check: `show ip interface brief`, `show ip route` (the VLAN subnets show as C, connected).
PCs in different VLANs can now ping each other.

### Step 5 - HSRP, two gateways sharing one address

On DIST-L3-1:

    interface vlan 10
     ip address 10.10.8.2 255.255.252.0
     standby version 2
     standby 10 ip 10.10.8.1
     standby 10 priority 110
     standby 10 preempt

On DIST-L3-2 the same but address `.3` and no priority line (default is 100).

PCs use 10.10.8.1. The switch with the highest priority answers for it. If it dies the other
takes over in a few seconds. `preempt` lets the better switch take the job back when it
returns.

Check: `show standby brief` on both. One says Active, the other Standby.

### Step 6 - spanning tree

Two uplinks from each room switch make a loop. Spanning tree blocks one so frames do not go
round forever.

    spanning-tree mode rapid-pvst
    spanning-tree vlan 10,70,99 priority 24576     (on DIST-L3-1)
    spanning-tree vlan 20,30 priority 28672        (on DIST-L3-1)

DIST-L3-2 has the numbers the other way round. Lowest priority becomes root. Make the root for
a VLAN the same switch that is HSRP active for it.

On PC ports:

    spanning-tree portfast
    spanning-tree bpduguard enable

PortFast skips the wait when a PC plugs in. BPDU guard shuts the port if somebody plugs a
switch into it.

Check: `show spanning-tree vlan 10`. On DIST-L3-1 it says "This bridge is the root". On SW-E230
one uplink is Root FWD and the other is Altn BLK.

### Step 7 - EtherChannel

    interface range gi1/0/2 - 3
     channel-group 1 mode active
    interface port-channel 1
     switchport mode trunk
     switchport trunk allowed vlan 10,20,30,70,99,101

Two cables act as one link. Spanning tree sees one port, so both carry traffic. `active` is
LACP. Both ends need the same speed, mode and VLAN list or the ports will not bundle.

Check: `show etherchannel summary`. You want `Po1(SU)` and `(P)` after each port. `(s)` or
`(I)` means that port did not join.

### Step 8 - OSPF

On a router or routed switch port:

    interface gi1/0/1
     no switchport
     ip address 10.10.0.22 255.255.255.252
    interface loopback 0
     ip address 10.10.255.5 255.255.255.255
    router ospf 1
     router-id 10.10.255.5
     passive-interface default
     no passive-interface gi1/0/1
     network 10.10.0.0 0.0.255.255 area 0

- `no switchport` makes a switch port behave like a router port
- the `network` line uses a **wildcard mask**, the opposite of a subnet mask
  (255.255.0.0 becomes 0.0.255.255). It means "run OSPF on every interface whose address
  starts with 10.10"
- `passive-interface` still advertises the subnet but sends no hellos out of it

On the edge router, to hand out the default route:

    ip route 0.0.0.0 0.0.0.0 203.0.113.1
    router ospf 1
     default-information originate

Check: `show ip ospf neighbor` (state FULL), `show ip route` (O routes, and `O*E2 0.0.0.0/0`).
If neighbors do not come up: both ends in the same subnet? same area? same hello timers?
is the interface passive by mistake?

### Step 9 - DHCP from one server

On SRV-DHCP > Services > DHCP, make a pool per VLAN (gateway, DNS, start address, how many).
The server is in VLAN 70 and DHCP is a broadcast, which routers do not forward. So on each
gateway:

    interface vlan 10
     ip helper-address 10.10.70.5

The switch picks the broadcast up and sends it to the server as a normal packet. The server
picks the pool that matches the gateway address it came from.

Check: PC > IP Configuration > DHCP. `ipconfig` shows an address from the right pool.

### Step 10 - ACLs

    ip access-list extended STUDENTS-IN
     permit udp any eq 68 any eq 67
     permit udp any host 10.10.70.10 eq 53
     permit tcp any host 10.10.70.10 eq 80
     deny ip any 10.0.0.0 0.255.255.255
     permit ip any any
    interface vlan 10
     ip access-group STUDENTS-IN in

How to read a line: `action protocol source destination port`.

- lines are checked top to bottom and the first match wins, so order matters
- there is an invisible `deny ip any any` at the end of every ACL
- `in` on the SVI means "traffic coming from the PCs in this VLAN"
- extended ACLs go near the source, standard ACLs near the destination
- the ACL does not remember connections. A reply is a new packet going the other way through
  the other VLAN's ACL. That is why the real ACLs have `established` and `echo-reply` lines

Check: `show access-lists` shows how many packets matched each line. Ping something and watch
which counter goes up. Simulation mode shows the exact device that drops the packet.

### Step 11 - NAT on the edge

    interface gi0/0
     ip nat inside
    interface gi0/0/0
     ip nat outside
    access-list 1 permit 10.10.0.0 0.0.255.255
    ip nat inside source list 1 interface gi0/0/0 overload
    ip nat inside source static 10.10.70.10 203.0.113.10

10.x addresses are private and do not work on the internet. `overload` (PAT) lets everybody
share the router's one public address by using different port numbers. The static line gives
the web server its own public address so people outside can reach it.

Check: ping 8.8.8.8 from a PC, then `show ip nat translations`.

### Step 12 - switch security

    interface range fa0/1 - 16
     switchport port-security
     switchport port-security maximum 2
     switchport port-security mac-address sticky
     switchport port-security violation restrict
    ip dhcp snooping
    ip dhcp snooping vlan 10,20
    no ip dhcp snooping information option
    interface range gi0/1 - 2
     ip dhcp snooping trust
    interface range fa0/17 - 24
     switchport access vlan 998
     shutdown

- port security: the port learns the PC's MAC and drops anything else
- DHCP snooping: only the trusted uplinks may send DHCP answers, so a student cannot run a
  fake DHCP server
- unused ports are off

Check: `show port-security`, `show ip dhcp snooping binding`.

### Step 13 - remote management

    ip domain-name rhs.lab
    crypto key generate rsa            (1024)
    ip ssh version 2
    access-list 10 permit 10.10.99.0 0.0.0.255
    line vty 0 15
     transport input ssh
     login local
     access-class 10 in
    interface vlan 99                  (layer 2 switches only)
     ip address 10.10.99.11 255.255.255.0
    ip default-gateway 10.10.99.1
    logging 10.10.70.20
    ntp server 10.10.70.20

### Step 14 - save

    copy running-config startup-config

on every device, then File > Save.

## Part C - the Python tool

The programs are in `tools/`. They need Python 3, which is already on a Mac. Nothing to install.

### With buttons

Double click `Start NetCheck.command` in the `tools` folder (or run `python3 netcheck_ui.py`).
A page opens in the browser with four tabs:

- **Lab** - every router and switch that is inside the Packet Tracer file, by layer, with its
  VLANs. Click one to read its running config (there is a search box). The green dot means the
  config in the lab is the same as the file in `configs/`. "Tidy the canvas" runs `pktlayout.py`
- **Configure** - click a device group (all access switches, both distribution switches, ...)
  or single devices, pick a change from the drop-down, fill in the boxes. **Preview** shows the
  commands for each device and, next to them, the lines that would change in the lab.
  **Write to the lab** puts the change into the lab file itself. "Save scripts only" just writes
  the scripts to a `changes` folder
- **Checks** - subnet calculator, check the plan, check the inventory, compare two configs,
  make a config for a new room switch
- **History** - every change that was made, and the copies of the lab from before each one.
  **Restore** puts the lab and the `configs` folder back (undo)

Packet Tracer devices cannot be reached over the network from outside Packet Tracer. But the
whole lab is one file, and the running config of every device is in it. So "Write to the
Packet Tracer lab" opens `RHS School Network.pkt`, changes the configs the way IOS would if the
commands were typed, and saves it again. Then open the lab in Packet Tracer and the devices
start with the new config. Rules:

- close the lab in Packet Tracer first. It only reads the file when opening it, and saving
  from Packet Tracer afterwards would put the old configs back
- a copy of the lab from before every change goes into `changes/backups`
- the file in `configs/` gets the same change, so the folder and the lab stay the same
- pasting still works too: open the device, CLI tab, log in, `enable`, paste the script.
  On real equipment the same scripts would be sent over SSH

The scripts are different per device where they need to be. "Allow a VLAN on trunks" reads each
device's saved config to find its trunk ports. "Create a VLAN gateway" gives DIST-L3-1 the .2
address and DIST-L3-2 the .3 address.

### By typing

Open Terminal in the project folder and go to the tools folder:

    cd tools

    python3 netcheck.py subnet 10.10.8.0/22

shows mask, wildcard mask, first and last host, broadcast. Try `10.10.10.0/22` and it tells you
that is really inside 10.10.8.0/22.

    python3 netcheck.py plan plan.csv

reads the addressing plan and checks every subnet is valid, gateways are inside their subnet,
and nothing overlaps.

    python3 netcheck.py inventory inventory.csv plan.csv

reads the device list and checks for duplicate names, duplicate IPs, addresses in the wrong
subnet, and that each subnet has room for its devices.

    python3 netcheck.py compare ../configs/SW-E230.txt ../configs/SW-E110.txt

shows the lines that differ between two configs. Two room switches should only differ in
hostname, descriptions and management IP. If anything else shows up, one of them was changed.
To compare a live device: `show running-config`, copy the text into a file, compare with the
one in `configs/`.

    python3 netcheck.py template E231 10.10.99.17

prints a full config for a new room switch, ready to paste into the CLI. Add a number at the
end for fewer than 15 student ports.

### Changing the lab file by typing

    python3 pktconfig.py list

shows the routers and switches in the lab file and the VLANs each switch knows.

    python3 pktconfig.py show SW-E230

prints the running config of one device as it is stored in the lab.

    python3 pktconfig.py check

compares every config in the lab with its file in `configs/`.

    python3 pktconfig.py apply SW-E230 mychange.txt

puts the commands from a text file into one device. Write the commands like you would type them
after `configure terminal`, in full (`switchport mode access`, not `sw mo acc`), with a space in
front of the lines that belong to an interface. Add `--dry-run` to only see what would change.
`apply` with a folder from `changes/` does every device that has a file in it. Mistakes are
caught before anything is written, for example a port that the switch does not have.
Things that need a running device (`show`, `ping`, `crypto key generate rsa`) cannot be written
into a file.

    python3 pktlayout.py

arranges the canvas again: devices on a grid, a coloured box per layer and room, and the text
notes. The text of the notes is at the top of `pktlayout.py`, change it there and run it again.

To see it catch mistakes, open `inventory.csv`, change an IP to one that is already used or to
something like 10.10.70.300, and run the inventory check again.

### How the programs work

- `plan.csv` and `inventory.csv` are plain spreadsheets (open them in Numbers or Excel)
- Python's built in `ipaddress` module does the subnet maths. `ipaddress.ip_network("10.10.8.0/22")`
  gives an object that knows its mask, broadcast and whether an address is inside it
- in `netcheck.py` each command is one function: `subnet_info`, `check_plan`, `check_inventory`,
  `compare`, `room_switch_template`. `main` at the bottom picks one from what you typed
- every check adds a sentence to a list called `problems`, and `report` prints the list
- `compare` throws away comment lines and uses `difflib` (built in) to find the differences
- in `netconfig.py` every change is a function that gets one device and returns the config
  lines for that device, or nothing if the change does not fit that device. `CATALOG` is the
  list the drop-down is made from
- a `.pkt` file is XML that Packet Tracer compresses (zlib) and encrypts (Twofish). `pktfile.py`
  undoes that with the standard library only, so the Twofish cipher is written out in it
- `pktconfig.py` finds each device in the XML, reads its config lines, and applies the commands
  with a few rules: a line that already exists is left alone, a command that can only be there
  once (`ip address`, `switchport mode`) replaces the old line, `no ...` removes a line, anything
  else is put next to the lines that look like it. VLANs go into the VLAN database of the switch,
  because that is where IOS keeps them (not in the running config)
- `netcheck_ui.py` is a very small web server that only this computer can reach. A button on
  the page sends a request, the server calls the matching function and sends the text back
