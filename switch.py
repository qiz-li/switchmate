"""Support for Switchmate."""
from __future__ import annotations

from datetime import timedelta

# pylint: disable=import-error
# import switchmate
import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

CONF_FLIP_ON_OFF = "flip_on_off"
DEFAULT_NAME = "Switchmate"

SCAN_INTERVAL = timedelta(seconds=10)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_FLIP_ON_OFF, default=False): cv.boolean,
    }
)

# PySwitchmate library

import asyncio
import logging

import bleak

CONNECT_LOCK = asyncio.Lock()

ON_KEY = b"\x01"
OFF_KEY = b"\x00"

_LOGGER = logging.getLogger(__name__)


class Switchmate:
    """Representation of a Switchmate."""

    def __init__(self, mac, flip_on_off=False) -> None:
        self._mac = mac
        self.state = False
        self._device = None
        self.available = False
        self._flip_on_off = flip_on_off
        self._handle = None

    async def _connect(self) -> bool:
        # Disconnect before reconnecting
        if self._device is not None:
            await self._disconnect()
        _LOGGER.debug("Connecting")
        self._device = bleak.BleakClient(self._mac)
        try:
            async with CONNECT_LOCK:
                await self._device.connect()
                if self._handle is None:
                    # Determine handle based on Switchmate model
                    self._handle = (
                        47
                        if await self._device.read_gatt_char(21) == b"Bright"
                        else 45
                    )
        except (bleak.BleakError, asyncio.exceptions.TimeoutError):
            _LOGGER.error(
                "Failed to connect to Switchmate",
                exc_info=logging.DEBUG >= _LOGGER.root.level,
            )
            return False
        return True

    async def _disconnect(self) -> bool:
        _LOGGER.debug("Disconnecting")
        try:
            async with CONNECT_LOCK:
                await self._device.disconnect()
        except (bleak.BleakError, asyncio.exceptions.TimeoutError):
            _LOGGER.error(
                "Failed to disconnect from Switchmate",
                exc_info=logging.DEBUG >= _LOGGER.root.level,
            )
            return False
        return True

    async def _communicate(self, key=None, retry=True) -> bool:
        try:
            if (
                self._device is None or not self._device.is_connected
            ) and not await self._connect():
                raise bleak.BleakError("No connection to Switchmate")
            async with CONNECT_LOCK:
                if key:
                    _LOGGER.debug("Sending key %s", key)
                    await self._device.write_gatt_char(self._handle, key, True)
                else:
                    _LOGGER.debug("Updating Switchmate state")
                    self.state = await self._device.read_gatt_char(
                        self._handle
                    ) == (ON_KEY if not self._flip_on_off else OFF_KEY)
        except (bleak.BleakError, asyncio.exceptions.TimeoutError):
            if retry:
                return await self._communicate(key, False)
            _LOGGER.error(
                "Cannot communicate with Switchmate",
                exc_info=logging.DEBUG >= _LOGGER.root.level,
            )
            self.available = False
            return False
        self.available = True
        return True

    async def update(self) -> bool:
        """Synchronize state with switch."""
        return await self._communicate()

    async def turn_on(self) -> bool:
        """Turn the switch on."""
        return await self._communicate(
            ON_KEY if not self._flip_on_off else OFF_KEY
        )

    async def turn_off(self) -> bool:
        """Turn the switch off."""
        return await self._communicate(
            OFF_KEY if not self._flip_on_off else ON_KEY
        )


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Perform the setup for Switchmate devices."""
    name = config.get(CONF_NAME)
    mac_addr = config[CONF_MAC]
    flip_on_off = config[CONF_FLIP_ON_OFF]
    add_entities([SwitchmateEntity(mac_addr, name, flip_on_off)], True)


class SwitchmateEntity(SwitchEntity):
    """Representation of a Switchmate."""

    def __init__(self, mac, name, flip_on_off) -> None:
        """Initialize the Switchmate."""

        self._mac = mac
        self._name = name
        self._device = Switchmate(mac=mac, flip_on_off=flip_on_off)

    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return self._mac.replace(":", "")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._device.available

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._name

    async def async_update(self) -> None:
        """Synchronize state with switch."""
        await self._device.update()

    @property
    def is_on(self) -> bool:
        """Return true if it is on."""
        return self._device.state

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        await self._device.turn_on()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        await self._device.turn_off()
