# C-MOVE Setup Guide for Horos

## The Problem

C-MOVE is failing because it requires a **two-way DICOM connection**:

1. **Query Connection**: Horos → Our Server (for browsing studies)
2. **Transfer Connection**: Our Server → Horos (for sending files)

The error `Connection refused` means our server cannot connect back to Horos to send the files.

## Why C-MOVE is Complex

Unlike C-GET (where files are sent back through the same connection), C-MOVE requires:

1. **Horos must act as a DICOM receiver** (not just a client)
2. **Horos must be listening on a specific port** for incoming connections
3. **Our server must know Horos's IP address and port**
4. **Network connectivity** must allow our server to connect to Horos

## Horos Configuration Required

### Step 1: Configure Horos as a DICOM Receiver

1. **Open Horos Preferences**
2. **Go to "Listener" tab**
3. **Enable "DICOM Listener"**
4. **Set a port** (e.g., 11113)
5. **Note the AE Title** (e.g., "HOROS")

### Step 2: Configure Network Access

1. **Check Horos is listening**:
   ```bash
   netstat -an | grep 11113
   ```

2. **Test connectivity from server to Horos**:
   ```bash
   telnet <horos-ip> 11113
   ```

### Step 3: Update Our Server Configuration

Update the AE configuration to point to Horos's actual IP:

```python
# In ae_config.py
DEFAULT_AE_CONFIG = {
    'HOROS': ('<horos-actual-ip>', 11113),  # Replace with real IP
    'AMRS-MACBOOK-PRO': ('<horos-actual-ip>', 11113),
}
```

## Alternative: Use C-GET Instead

C-GET is much simpler and works with most DICOM viewers including Horos:

1. **Single connection** (no need for Horos to be a receiver)
2. **Files sent back through same connection**
3. **Already working in our implementation**

## Testing C-MOVE

1. **Verify Horos is listening**:
   ```bash
   # On Horos machine
   netstat -an | grep 11113
   ```

2. **Test DICOM echo to Horos**:
   ```bash
   # From our server
   echoscu <horos-ip> 11113 -aet LAMRCE -aec HOROS
   ```

3. **Check firewall settings** on both machines

## Current Status

- ✅ **C-FIND**: Working (browsing studies)
- ✅ **C-GET**: Working (downloading files)
- ❌ **C-MOVE**: Requires Horos DICOM receiver setup

## Recommendation

**Use C-GET instead of C-MOVE** unless you specifically need C-MOVE for workflow reasons. C-GET provides the same functionality with much simpler setup.

If you must use C-MOVE, follow the Horos configuration steps above. 