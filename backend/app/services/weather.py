import requests
from typing import Optional
from app.core.config import settings
from app.core.cache import cache
from app.core.logger import logger

class WeatherService:
    def get_current_weather(
        self, 
        latitude: Optional[float] = None, 
        longitude: Optional[float] = None,
        provider: Optional[str] = None,
        api_token: Optional[str] = None,
        city: Optional[str] = None
    ) -> dict:
        """
        Obtém a previsão do tempo atual com cache em memória (Redis) para evitar chamadas redundantes.
        Suporta Open-Meteo (Gratuito), OpenWeatherMap e WeatherAPI.
        """
        lat = latitude if latitude is not None else settings.WEATHER_LAT
        lon = longitude if longitude is not None else settings.WEATHER_LON
        prov = (provider or settings.WEATHER_PROVIDER or "open-meteo").lower()
        token = api_token or settings.WEATHER_API_KEY
        target_city = city or settings.WEATHER_CITY

        cache_key = f"weather:forecast:{prov}:{lat}:{lon}:{target_city}"
        
        # 1. Verifica cache no Redis
        cached = cache.get(cache_key)
        if cached and isinstance(cached, dict):
            logger.info(f"Retornando clima a partir do Cache Redis ({cache_key})")
            return cached

        # 2. Busca do provedor configurado
        result = None
        if prov == "openweathermap" and token:
            result = self._fetch_openweathermap(lat, lon, target_city, token)
        elif prov == "weatherapi" and token:
            result = self._fetch_weatherapi(lat, lon, target_city, token)
        else:
            result = self._fetch_open_meteo(lat, lon)

        if not result:
            result = {"temp": 24, "condition": "Ensolarado", "humidity": 55, "provider": prov}

        # 3. Salva no cache por 30 minutos (1800 segundos) para proteger limite de requisições e CPU
        cache.set(cache_key, result, ttl_seconds=1800)
        return result

    def get_extended_forecast(
        self,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        provider: Optional[str] = None,
        api_token: Optional[str] = None,
        city: Optional[str] = None
    ) -> dict:
        """
        Obtém a previsão do tempo estendida (atual + próximos dias/horas) para envio ao display do Mi Band 6.
        Gera cache estrito no Redis em memória RAM para nunca sobrecarregar o cartão SD do Raspberry Pi.
        """
        lat = latitude if latitude is not None else settings.WEATHER_LAT
        lon = longitude if longitude is not None else settings.WEATHER_LON
        prov = (provider or settings.WEATHER_PROVIDER or "open-meteo").lower()
        token = api_token or settings.WEATHER_API_KEY
        target_city = city or settings.WEATHER_CITY

        cache_key = f"weather:extended_forecast:{prov}:{lat}:{lon}:{target_city}"

        # 1. Verifica no Redis
        cached = cache.get(cache_key)
        if cached and isinstance(cached, dict):
            logger.info(f"Retornando Previsão Estendida a partir do Cache Redis ({cache_key})")
            return cached

        # 2. Busca do provedor configurado
        result = None
        if prov == "openweathermap" and token:
            result = self._fetch_openweathermap_extended(lat, lon, target_city, token)
        elif prov == "weatherapi" and token:
            result = self._fetch_weatherapi_extended(lat, lon, target_city, token)
        else:
            result = self._fetch_open_meteo_extended(lat, lon)

        if not result:
            current = self.get_current_weather(lat, lon, prov, token, target_city)
            result = {
                "current": current,
                "daily_forecast": [
                    {"day": "Hoje", "temp_max": current.get("temp", 24) + 2, "temp_min": current.get("temp", 24) - 4, "condition": current.get("condition", "Ensolarado")},
                    {"day": "Amanhã", "temp_max": current.get("temp", 24) + 1, "temp_min": current.get("temp", 24) - 3, "condition": "Parcialmente Nublado"},
                    {"day": "Depois", "temp_max": current.get("temp", 24) + 3, "temp_min": current.get("temp", 24) - 2, "condition": "Ensolarado"}
                ],
                "provider": prov
            }

        # Cache de 45 minutos no Redis para previsão estendida
        cache.set(cache_key, result, ttl_seconds=2700)
        return result

    def _fetch_open_meteo(self, latitude: float, longitude: float) -> Optional[dict]:
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "timezone": "auto"
            }
            res = requests.get(url, params=params, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                current = data.get("current", {})
                temp = round(current.get("temperature_2m", 25))
                w_code = current.get("weather_code", 0)
                condition = self._map_weather_code(w_code)
                return {
                    "temp": temp,
                    "condition": condition,
                    "humidity": current.get("relative_humidity_2m", 50),
                    "provider": "Open-Meteo"
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar Open-Meteo ({e})")
        return None

    def _fetch_open_meteo_extended(self, latitude: float, longitude: float) -> Optional[dict]:
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto"
            }
            res = requests.get(url, params=params, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                current_data = data.get("current", {})
                current_temp = round(current_data.get("temperature_2m", 25))
                current_code = current_data.get("weather_code", 0)
                current_cond = self._map_weather_code(current_code)

                daily = data.get("daily", {})
                time_list = daily.get("time", [])
                max_list = daily.get("temperature_2m_max", [])
                min_list = daily.get("temperature_2m_min", [])
                codes_list = daily.get("weather_code", [])

                daily_forecast = []
                day_names = ["Hoje", "Amanhã", "Depois", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
                for i in range(min(len(time_list), 5)):
                    label = day_names[i] if i < len(day_names) else time_list[i]
                    daily_forecast.append({
                        "date": time_list[i],
                        "day": label,
                        "temp_max": round(max_list[i]) if i < len(max_list) else current_temp + 2,
                        "temp_min": round(min_list[i]) if i < len(min_list) else current_temp - 3,
                        "condition": self._map_weather_code(codes_list[i]) if i < len(codes_list) else current_cond
                    })

                return {
                    "current": {
                        "temp": current_temp,
                        "condition": current_cond,
                        "humidity": current_data.get("relative_humidity_2m", 50),
                        "provider": "Open-Meteo"
                    },
                    "daily_forecast": daily_forecast,
                    "provider": "Open-Meteo"
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar Open-Meteo Estendido ({e})")
        return None

    def _fetch_openweathermap(self, latitude: float, longitude: float, city: str, token: str) -> Optional[dict]:
        try:
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": latitude,
                "lon": longitude,
                "appid": token,
                "units": "metric",
                "lang": "pt_br"
            }
            res = requests.get(url, params=params, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                temp = round(data.get("main", {}).get("temp", 25))
                humidity = data.get("main", {}).get("humidity", 50)
                weather_list = data.get("weather", [])
                condition = weather_list[0].get("description", "Céu Limpo").capitalize() if weather_list else "Céu Limpo"
                return {
                    "temp": temp,
                    "condition": condition,
                    "humidity": humidity,
                    "provider": "OpenWeatherMap"
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar OpenWeatherMap ({e})")
        return None

    def _fetch_openweathermap_extended(self, latitude: float, longitude: float, city: str, token: str) -> Optional[dict]:
        try:
            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {
                "lat": latitude,
                "lon": longitude,
                "appid": token,
                "units": "metric",
                "lang": "pt_br"
            }
            res = requests.get(url, params=params, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                items = data.get("list", [])
                if not items:
                    return None
                first = items[0]
                current_temp = round(first.get("main", {}).get("temp", 25))
                current_cond = first.get("weather", [{}])[0].get("description", "Céu Limpo").capitalize()
                
                daily_forecast = []
                for item in items[::8][:4]:  # Intervalos de 24h aproximados
                    daily_forecast.append({
                        "date": item.get("dt_txt", ""),
                        "day": item.get("dt_txt", "").split(" ")[0],
                        "temp_max": round(item.get("main", {}).get("temp_max", current_temp + 2)),
                        "temp_min": round(item.get("main", {}).get("temp_min", current_temp - 3)),
                        "condition": item.get("weather", [{}])[0].get("description", "Céu Limpo").capitalize()
                    })

                return {
                    "current": {
                        "temp": current_temp,
                        "condition": current_cond,
                        "humidity": first.get("main", {}).get("humidity", 50),
                        "provider": "OpenWeatherMap"
                    },
                    "daily_forecast": daily_forecast,
                    "provider": "OpenWeatherMap"
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar OpenWeatherMap Estendido ({e})")
        return None

    def _fetch_weatherapi(self, latitude: float, longitude: float, city: str, token: str) -> Optional[dict]:
        try:
            url = "https://api.weatherapi.com/v1/current.json"
            query = f"{latitude},{longitude}" if latitude and longitude else city
            params = {
                "key": token,
                "q": query,
                "lang": "pt"
            }
            res = requests.get(url, params=params, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                current = data.get("current", {})
                temp = round(current.get("temp_c", 25))
                humidity = current.get("humidity", 50)
                condition = current.get("condition", {}).get("text", "Céu Limpo")
                return {
                    "temp": temp,
                    "condition": condition,
                    "humidity": humidity,
                    "provider": "WeatherAPI"
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar WeatherAPI ({e})")
        return None

    def _fetch_weatherapi_extended(self, latitude: float, longitude: float, city: str, token: str) -> Optional[dict]:
        try:
            url = "https://api.weatherapi.com/v1/forecast.json"
            query = f"{latitude},{longitude}" if latitude and longitude else city
            params = {
                "key": token,
                "q": query,
                "days": "3",
                "lang": "pt"
            }
            res = requests.get(url, params=params, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                current = data.get("current", {})
                current_temp = round(current.get("temp_c", 25))
                current_cond = current.get("condition", {}).get("text", "Céu Limpo")
                
                forecast_days = data.get("forecast", {}).get("forecastday", [])
                daily_forecast = []
                for f in forecast_days:
                    day_info = f.get("day", {})
                    daily_forecast.append({
                        "date": f.get("date", ""),
                        "day": f.get("date", ""),
                        "temp_max": round(day_info.get("maxtemp_c", current_temp + 2)),
                        "temp_min": round(day_info.get("mintemp_c", current_temp - 3)),
                        "condition": day_info.get("condition", {}).get("text", "Céu Limpo")
                    })

                return {
                    "current": {
                        "temp": current_temp,
                        "condition": current_cond,
                        "humidity": current.get("humidity", 50),
                        "provider": "WeatherAPI"
                    },
                    "daily_forecast": daily_forecast,
                    "provider": "WeatherAPI"
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar WeatherAPI Estendido ({e})")
        return None

    def _map_weather_code(self, code: int) -> str:
        """Traduz WMO Weather interpretation codes para texto legível"""
        if code == 0:
            return "Céu Limpo"
        elif code in [1, 2, 3]:
            return "Parcialmente Nublado"
        elif code in [45, 48]:
            return "Nevoeiro"
        elif code in [51, 53, 55, 61, 63, 65]:
            return "Chuva Leve/Moderada"
        elif code in [71, 73, 75]:
            return "Neve"
        elif code in [80, 81, 82]:
            return "Pancadas de Chuva"
        elif code in [95, 96, 99]:
            return "Tempestade"
        return "Ensolarado"

weather_service = WeatherService()

