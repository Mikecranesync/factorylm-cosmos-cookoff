"""
Fault Engine Module

Analyzes tag snapshots and detects faults based on sensor data and operational parameters.
Maintains fault history and severity tracking for the FactoryLM diagnostic system.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


class SeverityLevel(Enum):
    """Fault severity levels"""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class FaultCode:
    """Fault code definition"""
    code: str
    name: str
    severity: SeverityLevel
    description: str


@dataclass
class FaultRecord:
    """Individual fault occurrence record"""
    code: str
    name: str
    severity: SeverityLevel
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)


class FaultEngine:
    """
    Analyzes tag snapshots for fault conditions and maintains fault history.
    
    Fault Codes:
    - F001: Motor Overload (CRITICAL)
    - F002: Temperature High (WARNING)
    - F003: Conveyor Jam (CRITICAL)
    - F004: Sensor Failure (WARNING)
    - F005: Communication Loss (CRITICAL)
    - F006: Speed Deviation (WARNING)
    - F007: Voltage Fluctuation (WARNING)
    - F008: Emergency Stop (CRITICAL)
    """
    
    # Define all fault codes
    FAULT_CODES = {
        'F001': FaultCode('F001', 'Motor Overload', SeverityLevel.CRITICAL, 
                         'Motor current exceeds safe operating threshold'),
        'F002': FaultCode('F002', 'Temperature High', SeverityLevel.WARNING, 
                         'Equipment temperature exceeds warning threshold'),
        'F003': FaultCode('F003', 'Conveyor Jam', SeverityLevel.CRITICAL, 
                         'Conveyor belt is jammed or blocked'),
        'F004': FaultCode('F004', 'Sensor Failure', SeverityLevel.WARNING, 
                         'One or more sensors are not responding'),
        'F005': FaultCode('F005', 'Communication Loss', SeverityLevel.CRITICAL, 
                         'Lost communication with device or controller'),
        'F006': FaultCode('F006', 'Speed Deviation', SeverityLevel.WARNING, 
                         'Actual speed deviates significantly from setpoint'),
        'F007': FaultCode('F007', 'Voltage Fluctuation', SeverityLevel.WARNING, 
                         'Supply voltage is unstable or out of range'),
        'F008': FaultCode('F008', 'Emergency Stop', SeverityLevel.CRITICAL, 
                         'Emergency stop has been triggered'),
    }
    
    def __init__(self, sim_mode: bool = False):
        """
        Initialize the Fault Engine.
        
        Args:
            sim_mode: Enable simulation mode for testing
        """
        self.sim_mode = sim_mode
        self.active_faults: Dict[str, FaultRecord] = {}
        self.fault_history: List[FaultRecord] = []
        self._fault_thresholds = {
            'motor_current_max': 100.0,  # Amps
            'temperature_max': 80.0,      # Celsius
            'speed_deviation_max': 5.0,   # Percent
            'voltage_min': 220.0,         # Volts
            'voltage_max': 240.0,         # Volts
        }
    
    def analyze_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a tag snapshot for fault conditions.
        
        Args:
            snapshot: Dictionary containing tag data with keys like:
                     'motor_current', 'temperature', 'conveyor_speed', 
                     'sensor_status', 'communication_active', 'voltage', etc.
        
        Returns:
            Dictionary with analysis results including active faults and summary
        """
        new_faults = self._detect_faults(snapshot)
        
        # Update active faults
        for fault_code, fault_record in new_faults.items():
            if fault_code not in self.active_faults:
                self.active_faults[fault_code] = fault_record
                self.fault_history.append(fault_record)
        
        # Clear resolved faults
        resolved = [code for code in self.active_faults.keys() if code not in new_faults]
        for code in resolved:
            del self.active_faults[code]
        
        return {
            'timestamp': datetime.now().isoformat(),
            'active_faults': len(self.active_faults),
            'faults': [
                {
                    'code': fault.code,
                    'name': fault.name,
                    'severity': fault.severity.value,
                    'timestamp': fault.timestamp.isoformat(),
                    'details': fault.details
                }
                for fault in self.active_faults.values()
            ],
            'critical_count': sum(1 for f in self.active_faults.values() 
                                 if f.severity == SeverityLevel.CRITICAL),
            'warning_count': sum(1 for f in self.active_faults.values() 
                                if f.severity == SeverityLevel.WARNING),
        }
    
    def _detect_faults(self, snapshot: Dict[str, Any]) -> Dict[str, FaultRecord]:
        """
        Detect faults based on snapshot data.
        
        Args:
            snapshot: Tag snapshot dictionary
        
        Returns:
            Dictionary mapping fault codes to FaultRecord objects
        """
        faults = {}
        timestamp = datetime.now()
        
        # F001: Motor Overload
        motor_current = snapshot.get('motor_current', 0)
        if motor_current > self._fault_thresholds['motor_current_max']:
            faults['F001'] = FaultRecord(
                'F001', 'Motor Overload', SeverityLevel.CRITICAL, timestamp,
                {'motor_current': motor_current, 'max_allowed': self._fault_thresholds['motor_current_max']}
            )
        
        # F002: Temperature High
        temperature = snapshot.get('temperature', 0)
        if temperature > self._fault_thresholds['temperature_max']:
            faults['F002'] = FaultRecord(
                'F002', 'Temperature High', SeverityLevel.WARNING, timestamp,
                {'temperature': temperature, 'max_allowed': self._fault_thresholds['temperature_max']}
            )
        
        # F003: Conveyor Jam
        if snapshot.get('conveyor_jam', False):
            faults['F003'] = FaultRecord(
                'F003', 'Conveyor Jam', SeverityLevel.CRITICAL, timestamp,
                {'conveyor_blocked': True}
            )
        
        # F004: Sensor Failure
        if not snapshot.get('sensor_status', True):
            faults['F004'] = FaultRecord(
                'F004', 'Sensor Failure', SeverityLevel.WARNING, timestamp,
                {'sensor_responding': False}
            )
        
        # F005: Communication Loss
        if not snapshot.get('communication_active', True):
            faults['F005'] = FaultRecord(
                'F005', 'Communication Loss', SeverityLevel.CRITICAL, timestamp,
                {'communication_active': False}
            )
        
        # F006: Speed Deviation
        actual_speed = snapshot.get('actual_speed', 0)
        setpoint_speed = snapshot.get('setpoint_speed', 1)
        if setpoint_speed > 0:
            deviation = abs((actual_speed - setpoint_speed) / setpoint_speed) * 100
            if deviation > self._fault_thresholds['speed_deviation_max']:
                faults['F006'] = FaultRecord(
                    'F006', 'Speed Deviation', SeverityLevel.WARNING, timestamp,
                    {'actual_speed': actual_speed, 'setpoint_speed': setpoint_speed, 
                     'deviation_percent': deviation}
                )
        
        # F007: Voltage Fluctuation
        voltage = snapshot.get('voltage', 230)
        if not (self._fault_thresholds['voltage_min'] <= voltage <= self._fault_thresholds['voltage_max']):
            faults['F007'] = FaultRecord(
                'F007', 'Voltage Fluctuation', SeverityLevel.WARNING, timestamp,
                {'voltage': voltage, 'min_allowed': self._fault_thresholds['voltage_min'],
                 'max_allowed': self._fault_thresholds['voltage_max']}
            )
        
        # F008: Emergency Stop
        if snapshot.get('emergency_stop', False):
            faults['F008'] = FaultRecord(
                'F008', 'Emergency Stop', SeverityLevel.CRITICAL, timestamp,
                {'emergency_stop_active': True}
            )
        
        return faults
    
    def get_active_faults(self) -> List[Dict[str, Any]]:
        """Get list of currently active faults"""
        return [
            {
                'code': fault.code,
                'name': fault.name,
                'severity': fault.severity.value,
                'timestamp': fault.timestamp.isoformat(),
                'details': fault.details
            }
            for fault in self.active_faults.values()
        ]
    
    def get_fault_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get fault history"""
        history = self.fault_history if limit is None else self.fault_history[-limit:]
        return [
            {
                'code': fault.code,
                'name': fault.name,
                'severity': fault.severity.value,
                'timestamp': fault.timestamp.isoformat(),
                'details': fault.details
            }
            for fault in history
        ]
    
    def clear_fault(self, fault_code: str) -> bool:
        """
        Manually clear a fault (for testing or manual intervention).
        
        Args:
            fault_code: The fault code to clear
        
        Returns:
            True if fault was cleared, False if not found
        """
        if fault_code in self.active_faults:
            del self.active_faults[fault_code]
            return True
        return False
    
    def reset_history(self):
        """Clear fault history (useful for testing)"""
        self.fault_history = []
        self.active_faults = {}
    
    def set_threshold(self, threshold_name: str, value: float):
        """Update a fault threshold for testing"""
        if threshold_name in self._fault_thresholds:
            self._fault_thresholds[threshold_name] = value
