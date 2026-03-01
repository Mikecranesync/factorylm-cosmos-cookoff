"""
Linux WiFi Scanner Implementation

Real Raspberry Pi WiFi networking implementation using system tools.
Interfaces with iwlist and wpa_cli for network scanning and connection management.
"""

import subprocess
import re
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class NetworkInfo:
    """WiFi network information"""
    ssid: str
    signal_strength: int
    security: str
    channel: int
    frequency: str


class LinuxWifiScanner:
    """
    WiFi scanner for Linux-based systems (Raspberry Pi).
    
    Uses system commands iwlist and wpa_cli to scan and manage WiFi networks.
    """
    
    def __init__(self):
        """Initialize the Linux WiFi scanner"""
        self.interface = self._detect_wifi_interface()
        self.logger = logging.getLogger(__name__)
    
    def _detect_wifi_interface(self) -> str:
        """
        Detect the WiFi interface name.
        
        Returns:
            Interface name (e.g., 'wlan0') or 'wlan0' as fallback
        """
        try:
            result = subprocess.run(
                ['ip', 'link', 'show'],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Look for wlan or wlp interfaces
            for line in result.stdout.split('\n'):
                if 'wlan' in line or 'wlp' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        interface = parts[1].strip()
                        if interface:
                            return interface
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            self.logger.warning(f"Failed to detect WiFi interface: {e}")
        
        return 'wlan0'  # Default fallback
    
    def scan_networks(self) -> List[Dict[str, Any]]:
        """
        Scan for available WiFi networks.
        
        Returns:
            List of dictionaries with network information:
            [
                {
                    'ssid': 'NetworkName',
                    'signal_strength': -45,  # dBm
                    'security': 'WPA2/WPA3',
                    'channel': 6,
                    'frequency': '2.4 GHz'
                },
                ...
            ]
        
        Raises:
            RuntimeError: If scan fails
        """
        networks = []
        
        try:
            # Run iwlist scan command
            result = subprocess.run(
                ['sudo', 'iwlist', self.interface, 'scan'],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                error_msg = f"iwlist scan failed: {result.stderr}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Parse the output
            current_cell = None
            output = result.stdout
            
            # Split into cell blocks
            cells = re.split(r'Cell \d+', output)
            
            for cell in cells[1:]:  # Skip first empty split
                try:
                    network_info = self._parse_cell(cell)
                    if network_info:
                        networks.append(network_info)
                except Exception as e:
                    self.logger.warning(f"Failed to parse cell: {e}")
                    continue
            
            return networks
        
        except subprocess.TimeoutExpired:
            error_msg = "WiFi scan timed out"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        except FileNotFoundError:
            error_msg = "iwlist command not found. Install wireless-tools package."
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"WiFi scan error: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def _parse_cell(self, cell_text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a cell block from iwlist output.
        
        Args:
            cell_text: Text block for a single cell
        
        Returns:
            Dictionary with network info or None if parsing fails
        """
        try:
            # Extract SSID
            ssid_match = re.search(r'ESSID:"([^"]*)"', cell_text)
            if not ssid_match:
                return None
            ssid = ssid_match.group(1)
            
            # Extract signal strength
            signal_match = re.search(r'Signal level[=:](-?\d+)', cell_text)
            signal_strength = int(signal_match.group(1)) if signal_match else -100
            
            # Extract channel/frequency
            freq_match = re.search(r'Frequency[=:]([0-9.]+)\s*GHz', cell_text)
            frequency = freq_match.group(1) if freq_match else "2.4"
            
            # Extract channel (derived from frequency)
            channel = self._freq_to_channel(frequency)
            
            # Extract security
            security = self._extract_security(cell_text)
            
            return {
                'ssid': ssid,
                'signal_strength': signal_strength,
                'security': security,
                'channel': channel,
                'frequency': frequency + ' GHz'
            }
        
        except Exception as e:
            self.logger.warning(f"Error parsing cell: {e}")
            return None
    
    def _freq_to_channel(self, freq_ghz: str) -> int:
        """
        Convert frequency in GHz to WiFi channel number.
        
        Args:
            freq_ghz: Frequency as string like "2.437"
        
        Returns:
            Channel number
        """
        try:
            freq = float(freq_ghz) * 1000  # Convert to MHz
            if 2400 < freq < 2500:
                # 2.4 GHz band: channel = (freq - 2407) / 5
                channel = int((freq - 2407) / 5)
                return max(1, min(14, channel))
            elif 5000 < freq < 6000:
                # 5 GHz band: channel = (freq - 5000) / 5
                channel = int((freq - 5000) / 5)
                return max(36, min(196, channel))
        except (ValueError, TypeError):
            pass
        
        return 1  # Default fallback
    
    def _extract_security(self, cell_text: str) -> str:
        """
        Extract security information from cell text.
        
        Args:
            cell_text: Text block for a single cell
        
        Returns:
            Security string (WPA2, WPA3, WEP, Open, etc.)
        """
        security_types = []
        
        if 'WPA3' in cell_text:
            security_types.append('WPA3')
        if 'WPA2' in cell_text or 'WPA ' in cell_text:
            security_types.append('WPA2')
        if 'WEP' in cell_text:
            security_types.append('WEP')
        
        if security_types:
            return '/'.join(security_types)
        
        return 'Open'
    
    def connect_network(self, ssid: str, password: Optional[str] = None, 
                       security: str = 'WPA2') -> bool:
        """
        Connect to a WiFi network.
        
        Args:
            ssid: Network SSID
            password: Network password (None for open networks)
            security: Security type ('WPA2', 'WPA3', 'WEP', 'Open')
        
        Returns:
            True if connection successful, False otherwise
        
        Raises:
            RuntimeError: If connection fails
        """
        try:
            # Validate inputs
            if not ssid:
                raise ValueError("SSID cannot be empty")
            
            if security.upper() != 'OPEN' and not password:
                raise ValueError("Password required for secured networks")
            
            self.logger.info(f"Attempting to connect to {ssid} ({security})")
            
            # Create wpa_supplicant configuration
            wpa_config = self._create_wpa_config(ssid, password, security)
            
            # Write config to temp file
            config_path = '/tmp/wpa_supplicant_temp.conf'
            with open(config_path, 'w') as f:
                f.write(wpa_config)
            
            # Reconfigure wpa_supplicant
            reconfigure_cmd = ['sudo', 'wpa_cli', '-i', self.interface, 'reconfigure']
            result = subprocess.run(reconfigure_cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.logger.warning(f"wpa_cli reconfigure returned {result.returncode}")
            
            # Alternative: use wpa_cli add_network and set commands
            result = self._wpa_cli_connect(ssid, password, security)
            
            if result:
                self.logger.info(f"Successfully connected to {ssid}")
                return True
            else:
                error_msg = f"Failed to connect to {ssid}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
        
        except subprocess.TimeoutExpired:
            error_msg = "Connection attempt timed out"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def _wpa_cli_connect(self, ssid: str, password: Optional[str], 
                        security: str) -> bool:
        """
        Use wpa_cli to connect to a network.
        
        Args:
            ssid: Network SSID
            password: Network password
            security: Security type
        
        Returns:
            True if successful
        """
        try:
            # Add new network
            add_result = subprocess.run(
                ['sudo', 'wpa_cli', '-i', self.interface, 'add_network'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if add_result.returncode != 0:
                return False
            
            network_id = add_result.stdout.strip()
            
            # Set SSID
            subprocess.run(
                ['sudo', 'wpa_cli', '-i', self.interface, 'set_network', 
                 network_id, 'ssid', f'"{ssid}"'],
                capture_output=True,
                timeout=5
            )
            
            # Set password if required
            if password:
                subprocess.run(
                    ['sudo', 'wpa_cli', '-i', self.interface, 'set_network',
                     network_id, 'psk', f'"{password}"'],
                    capture_output=True,
                    timeout=5
                )
            else:
                # Open network
                subprocess.run(
                    ['sudo', 'wpa_cli', '-i', self.interface, 'set_network',
                     network_id, 'key_mgmt', 'NONE'],
                    capture_output=True,
                    timeout=5
                )
            
            # Enable network
            enable_result = subprocess.run(
                ['sudo', 'wpa_cli', '-i', self.interface, 'enable_network', network_id],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Save config
            subprocess.run(
                ['sudo', 'wpa_cli', '-i', self.interface, 'save_config'],
                capture_output=True,
                timeout=5
            )
            
            return enable_result.returncode == 0
        
        except Exception as e:
            self.logger.error(f"wpa_cli connection error: {e}")
            return False
    
    def _create_wpa_config(self, ssid: str, password: Optional[str], 
                          security: str) -> str:
        """
        Create wpa_supplicant configuration.
        
        Args:
            ssid: Network SSID
            password: Network password
            security: Security type
        
        Returns:
            Configuration string
        """
        config = "ctrl_interface=/var/run/wpa_supplicant\n"
        config += "update_config=1\n\n"
        config += "network={\n"
        config += f'    ssid="{ssid}"\n'
        
        if password:
            config += f'    psk="{password}"\n'
        else:
            config += "    key_mgmt=NONE\n"
        
        config += "}\n"
        
        return config
    
    def get_connection_status(self) -> Dict[str, Any]:
        """
        Get current WiFi connection status.
        
        Returns:
            Dictionary with connection information
        """
        try:
            result = subprocess.run(
                ['sudo', 'wpa_cli', '-i', self.interface, 'status'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            status = {}
            for line in result.stdout.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    status[key.strip()] = value.strip()
            
            return status
        
        except Exception as e:
            self.logger.error(f"Failed to get connection status: {e}")
            return {}
    
    def disconnect(self) -> bool:
        """
        Disconnect from current WiFi network.
        
        Returns:
            True if successful
        """
        try:
            result = subprocess.run(
                ['sudo', 'wpa_cli', '-i', self.interface, 'disconnect'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            return result.returncode == 0
        
        except Exception as e:
            self.logger.error(f"Failed to disconnect: {e}")
            return False
