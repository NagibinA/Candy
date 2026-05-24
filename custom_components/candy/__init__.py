"""The Candy integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import async_timeout
import aiohttp
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .client import CandyClient, WashingMachineStatus

from .const import *

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Candy from a config entry."""

    ip_address = config_entry.data[CONF_IP_ADDRESS]
    encryption_key = config_entry.data.get(CONF_PASSWORD, "")
    use_encryption = config_entry.data.get(CONF_KEY_USE_ENCRYPTION, True)

    session = async_get_clientsession(hass)
    client = CandyClient(session, ip_address, encryption_key, use_encryption)

    async def update_status():
        try:
            async with async_timeout.timeout(40):
                status = await client.status_with_retry()
                _LOGGER.debug("Fetched status: %s", status)
                return status
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {repr(err)}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_interval=timedelta(seconds=60),
        update_method=update_status,
    )

    await coordinator.async_config_entry_first_refresh()

    # ========== ДОБАВЛЯЕМ СЕРВИС STOP_WASH ==========
    async def handle_stop_wash(call: ServiceCall):
        """Handle stop wash service."""
        _LOGGER.info("Stopping washing machine")
        
        # Формируем URL как в вашем примере: encrypted=0, Write=1, StSt=0
        url = f"http://{ip_address}/http-write.json?encrypted=0&Write=1&StSt=0"
        
        _LOGGER.debug("Stop wash URL: %s", url)
        
        try:
            async with async_timeout.timeout(10):
                async with session.get(url) as resp:
                    response_text = await resp.text()
                    
                    # Логируем ответ для отладки
                    _LOGGER.debug("API response: %s", response_text)
                    
                    if resp.status == 200:
                        _LOGGER.info("✅ Wash stopped successfully")
                        
                        # Принудительно обновляем статус
                        await coordinator.async_request_refresh()
                        
                        # Возвращаем успех (опционально)
                        return {"success": True, "response": response_text}
                    else:
                        _LOGGER.error("❌ Failed to stop wash. Status: %s", resp.status)
                        return {"success": False, "error": f"HTTP {resp.status}"}
                        
        except asyncio.TimeoutError:
            _LOGGER.error("⏰ Timeout while stopping wash")
            return {"success": False, "error": "Timeout"}
        except aiohttp.ClientError as err:
            _LOGGER.error("🔌 Network error: %s", err)
            return {"success": False, "error": str(err)}
        except Exception as err:
            _LOGGER.error("💥 Unexpected error: %s", err)
            return {"success": False, "error": str(err)}

    # Регистрируем сервис
    hass.services.async_register(
        DOMAIN,
        "stop_wash",
        handle_stop_wash
    )
    # ========== КОНЕЦ СЕРВИСА ==========

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        DATA_KEY_COORDINATOR: coordinator
    }

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Удаляем сервис при выгрузке
    hass.services.async_remove(DOMAIN, "stop_wash")
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        del hass.data[DOMAIN]

    return unload_ok