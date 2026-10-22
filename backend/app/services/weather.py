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
            cur_temp = current.get("temp", 24)
            weekdays = ["Hoje", "Amanhã", "Depois", "Quarta", "Quinta", "Sexta", "Sábado"]
            daily_list = []
            for i, d in enumerate(weekdays):
                daily_list.append({
                    "day": d,
                    "temp_max": cur_temp + (2 if i % 2 == 0 else 1),
                    "temp_min": cur_temp - (4 if i % 2 == 0 else 3),
                    "condition": current.get("condition", "Ensolarado"),
                    "code": current.get("code", 0)
                })
            result = {
                "current": current,
                "daily_forecast": daily_list,
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
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
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
                    "code": w_code,
                    "humidity": current.get("relative_humidity_2m", 50),
                    "wind_speed": round(current.get("wind_speed_10m", 0)),
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
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
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
                sunrise_list = daily.get("sunrise", [])
                sunset_list = daily.get("sunset", [])

                daily_forecast = []
                pt_weekdays = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                from datetime import date
                for i in range(min(len(time_list), 7)):
                    iso_date = time_list[i]
                    if i == 0:
                        label = "Hoje"
                    elif i == 1:
                        label = "Amanhã"
                    else:
                        try:
                            d_obj = date.fromisoformat(iso_date)
                            label = pt_weekdays[d_obj.weekday()]
                        except Exception:
                            label = iso_date

                    code_val = codes_list[i] if i < len(codes_list) else current_code
                    daily_forecast.append({
                        "date": iso_date,
                        "day": label,
                        "code": code_val,
                        "temp_max": round(max_list[i]) if i < len(max_list) else current_temp + 2,
                        "temp_min": round(min_list[i]) if i < len(min_list) else current_temp - 3,
                        "condition": self._map_weather_code(code_val)
                    })

                today_sunrise = sunrise_list[0].split("T")[1] if sunrise_list and "T" in sunrise_list[0] else "06:00"
                today_sunset = sunset_list[0].split("T")[1] if sunset_list and "T" in sunset_list[0] else "18:00"

                return {
                    "current": {
                        "temp": current_temp,
                        "condition": current_cond,
                        "code": current_code,
                        "humidity": current_data.get("relative_humidity_2m", 50),
                        "wind_speed": round(current_data.get("wind_speed_10m", 0)),
                        "sunrise": today_sunrise,
                        "sunset": today_sunset,
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
                code = weather_list[0].get("id", 800) if weather_list else 800
                return {
                    "temp": temp,
                    "condition": condition,
                    "code": code,
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
                first_weather = first.get("weather", [{}])[0]
                current_cond = first_weather.get("description", "Céu Limpo").capitalize()
                current_code = first_weather.get("id", 800)
                
                # Agrupar por data (YYYY-MM-DD)
                from datetime import date, timedelta
                grouped_by_date = {}
                for item in items:
                    dt_txt = item.get("dt_txt", "")
                    d_key = dt_txt.split(" ")[0] if " " in dt_txt else dt_txt[:10]
                    if d_key not in grouped_by_date:
                        grouped_by_date[d_key] = []
                    grouped_by_date[d_key].append(item)

                daily_forecast = []
                pt_weekdays = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                sorted_dates = sorted(grouped_by_date.keys())
                for idx, d_key in enumerate(sorted_dates[:7]):
                    day_items = grouped_by_date[d_key]
                    maxs = [it.get("main", {}).get("temp_max", current_temp) for it in day_items]
                    mins = [it.get("main", {}).get("temp_min", current_temp) for it in day_items]
                    mid_weather = day_items[len(day_items)//2].get("weather", [{}])[0]
                    
                    if idx == 0:
                        label = "Hoje"
                    elif idx == 1:
                        label = "Amanhã"
                    else:
                        try:
                            label = pt_weekdays[date.fromisoformat(d_key).weekday()]
                        except Exception:
                            label = d_key

                    daily_forecast.append({
                        "date": d_key,
                        "day": label,
                        "temp_max": round(max(maxs)),
                        "temp_min": round(min(mins)),
                        "condition": mid_weather.get("description", "Céu Limpo").capitalize(),
                        "code": mid_weather.get("id", 800)
                    })

                # Se a API retornou menos de 7 dias (ex: 5 dias), extrapola até completar 7
                last_dt = date.fromisoformat(daily_forecast[-1]["date"]) if daily_forecast else date.today()
                while len(daily_forecast) < 7:
                    last_dt = last_dt + timedelta(days=1)
                    idx = len(daily_forecast)
                    label = "Amanhã" if idx == 1 else pt_weekdays[last_dt.weekday()]
                    daily_forecast.append({
                        "date": last_dt.isoformat(),
                        "day": label,
                        "temp_max": current_temp + (2 if idx % 2 == 0 else 1),
                        "temp_min": current_temp - (4 if idx % 2 == 0 else 3),
                        "condition": current_cond,
                        "code": current_code
                    })

                return {
                    "current": {
                        "temp": current_temp,
                        "condition": current_cond,
                        "code": current_code,
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
                code = current.get("condition", {}).get("code", 1000)
                return {
                    "temp": temp,
                    "condition": condition,
                    "code": code,
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
                "days": "7",
                "lang": "pt"
            }
            res = requests.get(url, params=params, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                current = data.get("current", {})
                current_temp = round(current.get("temp_c", 25))
                current_cond = current.get("condition", {}).get("text", "Céu Limpo")
                current_code = current.get("condition", {}).get("code", 1000)
                
                from datetime import date, timedelta
                pt_weekdays = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                forecast_days = data.get("forecast", {}).get("forecastday", [])
                daily_forecast = []
                for idx, f in enumerate(forecast_days[:7]):
                    day_info = f.get("day", {})
                    date_str = f.get("date", "")
                    if idx == 0:
                        label = "Hoje"
                    elif idx == 1:
                        label = "Amanhã"
                    else:
                        try:
                            label = pt_weekdays[date.fromisoformat(date_str).weekday()]
                        except Exception:
                            label = date_str

                    daily_forecast.append({
                        "date": date_str,
                        "day": label,
                        "temp_max": round(day_info.get("maxtemp_c", current_temp + 2)),
                        "temp_min": round(day_info.get("mintemp_c", current_temp - 3)),
                        "condition": day_info.get("condition", {}).get("text", "Céu Limpo"),
                        "code": day_info.get("condition", {}).get("code", 1000)
                    })

                # Extrapolar até 7 dias se o plano da WeatherAPI retornar apenas 3 dias
                last_dt = date.fromisoformat(daily_forecast[-1]["date"]) if daily_forecast else date.today()
                while len(daily_forecast) < 7:
                    last_dt = last_dt + timedelta(days=1)
                    idx = len(daily_forecast)
                    label = "Amanhã" if idx == 1 else pt_weekdays[last_dt.weekday()]
                    daily_forecast.append({
                        "date": last_dt.isoformat(),
                        "day": label,
                        "temp_max": current_temp + (2 if idx % 2 == 0 else 1),
                        "temp_min": current_temp - (4 if idx % 2 == 0 else 3),
                        "condition": current_cond,
                        "code": current_code
                    })

                return {
                    "current": {
                        "temp": current_temp,
                        "condition": current_cond,
                        "code": current_code,
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

    def search_cities(
        self,
        query: str,
        provider: Optional[str] = None,
        api_token: Optional[str] = None
    ) -> list:
        """
        Pesquisa cidades por nome no serviço de clima ativo ou Open-Meteo Geocoding.
        Retorna lista de dicionários normalizados com:
        [{"name": "...", "region": "...", "country": "...", "latitude": ..., "longitude": ..., "display_name": "..."}]
        """
        clean_query = (query or "").strip()
        if len(clean_query) < 2:
            return []

        prov = (provider or settings.WEATHER_PROVIDER or "open-meteo").lower()
        token = api_token or settings.WEATHER_API_KEY
        cache_key = f"weather:city:search:{prov}:{clean_query.lower()}"

        cached = cache.get(cache_key)
        if cached and isinstance(cached, list):
            return cached

        results = []
        try:
            if prov == "weatherapi" and token:
                url = "https://api.weatherapi.com/v1/search.json"
                params = {"key": token, "q": clean_query}
                res = requests.get(url, params=params, timeout=5.0)
                if res.status_code == 200:
                    for item in res.json():
                        name = item.get("name", "")
                        region = item.get("region", "")
                        country = item.get("country", "")
                        disp = f"{name}, {region} - {country}" if region else f"{name} - {country}"
                        results.append({
                            "name": name,
                            "region": region,
                            "country": country,
                            "latitude": item.get("lat"),
                            "longitude": item.get("lon"),
                            "display_name": disp
                        })

            elif prov == "openweathermap" and token:
                url = "https://api.openweathermap.org/geo/1.0/direct"
                params = {"q": clean_query, "limit": 6, "appid": token}
                res = requests.get(url, params=params, timeout=5.0)
                if res.status_code == 200:
                    for item in res.json():
                        name = item.get("name", "")
                        state = item.get("state", "")
                        country = item.get("country", "")
                        disp = f"{name}, {state} - {country}" if state else f"{name} - {country}"
                        results.append({
                            "name": name,
                            "region": state,
                            "country": country,
                            "latitude": item.get("lat"),
                            "longitude": item.get("lon"),
                            "display_name": disp
                        })

            # Se não teve resultados ou é open-meteo (ou provedores sem token), usa Open-Meteo Geocoding
            if not results:
                url = "https://geocoding-api.open-meteo.com/v1/search"
                params = {"name": clean_query, "count": 6, "language": "pt", "format": "json"}
                res = requests.get(url, params=params, timeout=5.0)
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get("results", []):
                        name = item.get("name", "")
                        admin1 = item.get("admin1", "")
                        country = item.get("country", "")
                        disp = f"{name}, {admin1} - {country}" if admin1 else f"{name} - {country}"
                        results.append({
                            "name": name,
                            "region": admin1,
                            "country": country,
                            "latitude": item.get("latitude"),
                            "longitude": item.get("longitude"),
                            "display_name": disp
                        })
        except Exception as e:
            logger.warning(f"Erro ao pesquisar cidades ({e})")

        if results:
            cache.set(cache_key, results, ttl_seconds=86400)
        return results

    def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
        provider: Optional[str] = None,
        api_token: Optional[str] = None
    ) -> Optional[dict]:
        """
        Descobre o nome da cidade a partir das coordenadas geográficas (lat, lon).
        """
        cache_key = f"weather:city:reverse:{latitude:.3f}:{longitude:.3f}"
        cached = cache.get(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        prov = (provider or settings.WEATHER_PROVIDER or "open-meteo").lower()
        token = api_token or settings.WEATHER_API_KEY
        result = None

        try:
            # 1. Tenta OpenWeatherMap se houver token
            if prov == "openweathermap" and token:
                url = "https://api.openweathermap.org/geo/1.0/reverse"
                params = {"lat": latitude, "lon": longitude, "limit": 1, "appid": token}
                res = requests.get(url, params=params, timeout=5.0)
                if res.status_code == 200:
                    items = res.json()
                    if items:
                        item = items[0]
                        name = item.get("name", "")
                        state = item.get("state", "")
                        country = item.get("country", "")
                        disp = f"{name}, {state} - {country}" if state else f"{name} - {country}"
                        result = {
                            "name": name,
                            "region": state,
                            "country": country,
                            "latitude": latitude,
                            "longitude": longitude,
                            "display_name": disp
                        }

            # 2. BigDataCloud Client Reverse Geocode (Gratuito, sem chave, suporte nativo pt-BR)
            if not result:
                url = "https://api.bigdatacloud.net/data/reverse-geocode-client"
                params = {"latitude": latitude, "longitude": longitude, "localityLanguage": "pt"}
                res = requests.get(url, params=params, timeout=5.0)
                if res.status_code == 200:
                    data = res.json()
                    city = data.get("city") or data.get("locality") or data.get("principalSubdivision") or "Minha Localização"
                    region = data.get("principalSubdivision", "")
                    country = data.get("countryName", "")
                    disp = f"{city}, {region} - {country}" if region and region != city else f"{city} - {country}"
                    result = {
                        "name": city,
                        "region": region,
                        "country": country,
                        "latitude": latitude,
                        "longitude": longitude,
                        "display_name": disp
                    }
        except Exception as e:
            logger.warning(f"Erro no reverse geocoding ({e})")

        if result:
            cache.set(cache_key, result, ttl_seconds=86400)
        return result

    def detect_location_by_ip(self) -> Optional[dict]:
        """
        Detecta a localização do computador / servidor com base no endereço IP público.
        """
        cache_key = "weather:location:ip_detected"
        cached = cache.get(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        result = None
        # 1. Tentar ipapi.co
        try:
            res = requests.get("https://ipapi.co/json/", headers={"User-Agent": "MiBandServer/1.0"}, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                city = data.get("city")
                if city:
                    region = data.get("region", "")
                    country = data.get("country_name", "")
                    lat = data.get("latitude")
                    lon = data.get("longitude")
                    disp = f"{city}, {region} - {country}" if region else f"{city} - {country}"
                    result = {
                        "name": city,
                        "region": region,
                        "country": country,
                        "latitude": lat,
                        "longitude": lon,
                        "display_name": disp
                    }
        except Exception as e:
            logger.warning(f"Erro ao detectar IP via ipapi.co ({e})")

        # 2. Fallback ip-api.com
        if not result:
            try:
                res = requests.get("http://ip-api.com/json/", timeout=5.0)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("status") == "success":
                        city = data.get("city")
                        region = data.get("regionName", "")
                        country = data.get("country", "")
                        lat = data.get("lat")
                        lon = data.get("lon")
                        disp = f"{city}, {region} - {country}" if region else f"{city} - {country}"
                        result = {
                            "name": city,
                            "region": region,
                            "country": country,
                            "latitude": lat,
                            "longitude": lon,
                            "display_name": disp
                        }
            except Exception as e:
                logger.warning(f"Erro ao detectar IP via ip-api.com ({e})")

        if result:
            cache.set(cache_key, result, ttl_seconds=3600)
        return result

weather_service = WeatherService()


