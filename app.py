import ee
import json
import os
import traceback
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime

# Загружаем переменные окружения
load_dotenv()

# Инициализация Flask
app = Flask(__name__)
CORS(app)  # Разрешаем запросы с любых доменов

# Конфигурация
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

def initialize_earth_engine():
    """Инициализация Earth Engine"""
    try:
        print("\n🔄 Инициализация Earth Engine...")
        
        # Получаем credentials из переменных окружения (GitHub Secrets)
        gee_credentials = os.environ.get("GEE_CREDENTIALS")
        
        if not gee_credentials:
            raise ValueError("GEE_CREDENTIALS не найдены в переменных окружения")
        
        # Парсим JSON credentials
        service_account_info = json.loads(gee_credentials)
        
        # Создаем credentials для Earth Engine
        credentials = ee.ServiceAccountCredentials(
            service_account_info["client_email"],
            key_data=json.dumps(service_account_info)
        )
        
        # Инициализируем Earth Engine
        ee.Initialize(credentials)
        print("✅ Earth Engine инициализирован")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка инициализации Earth Engine: {str(e)}")
        return False

def mask_clouds(img):
    """Маскировка облаков"""
    scl = img.select("SCL")
    allowed = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
    return img.updateMask(allowed).resample("bilinear")

def calculate_ndvi(img):
    """Расчет NDVI индекса"""
    ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
    return img.addBands(ndvi)

def calculate_ndwi(img):
    """Расчет NDWI индекса"""
    ndwi = img.normalizedDifference(['B3', 'B8']).rename('NDWI')
    return img.addBands(ndwi)

@app.route('/')
def index():
    """Главная страница - отдаем наш HTML"""
    return render_template('index.html')

@app.route('/api/get_sentinel_image', methods=['POST'])
def get_sentinel_image():
    """API для получения спутникового снимка"""
    try:
        # Получаем параметры из запроса
        data = request.json
        bounds = data['bounds']
        geometry = ee.Geometry.Rectangle(bounds)
        start_date = data['start_date']
        end_date = data['end_date']
        cloud_filter = data.get('cloud_filter', 30)
        enable_smoothing = data.get('smoothing', True)
        layer_type = data.get('layer', 'TRUE_COLOR')
        
        print(f"📡 Запрос снимка: {start_date} - {end_date}, облачность < {cloud_filter}%, слой: {layer_type}")
        
        # Конфигурация для разных типов слоев
        band_configs = {
            'TRUE_COLOR': {
                'bands': ['B4', 'B3', 'B2'], 
                'min': '0,0,0', 
                'max': '3000,3000,3000',
                'description': 'Настоящие цвета (RGB)'
            },
            'FALSE_COLOR': {
                'bands': ['B8', 'B4', 'B3'], 
                'min': '0,0,0', 
                'max': '3000,3000,3000',
                'description': 'Ложные цвета'
            },
            'NDVI': {
                'bands': ['NDVI'], 
                'min': '-1', 
                'max': '1',
                'palette': ['red', 'yellow', 'green'],
                'description': 'NDVI - Вегетационный индекс'
            },
            'NDWI': {
                'bands': ['NDWI'], 
                'min': '-1', 
                'max': '1', 
                'palette': ['white', 'blue'],
                'description': 'NDWI - Водный индекс'
            }
        }
        
        config = band_configs.get(layer_type, band_configs['TRUE_COLOR'])
        
        # Формируем коллекцию снимков
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_date, end_date)
            .filterBounds(geometry)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_filter))
        )
        
        # Добавляем вычисление индексов если нужно
        if layer_type == 'NDVI':
            collection = collection.map(calculate_ndvi)
        elif layer_type == 'NDWI':
            collection = collection.map(calculate_ndwi)
        
        # Применяем маскировку облаков если включено сглаживание
        if enable_smoothing:
            collection = collection.map(mask_clouds)
        
        # Создаем мозаику
        mosaic = collection.median()
        
        # Формируем параметры для визуализации
        vis_params = {
            "bands": config['bands'],
            "min": config.get('min', '0'),
            "max": config.get('max', '3000'),
            "region": geometry
        }
        
        # Добавляем палитру для индексов
        if 'palette' in config:
            vis_params["palette"] = config['palette']
        
        # Получаем URL для тайлов
        tile_info = ee.data.getMapId({
            "image": mosaic,
            **vis_params
        })
        
        # Формируем URL для тайлов
        map_id = tile_info["mapid"]
        tile_url = f"https://earthengine.googleapis.com/v1/maps/{map_id}/tiles/{{z}}/{{x}}/{{y}}"
        
        image_count = collection.size().getInfo()
        
        print(f"✅ Успешно: найдено {image_count} снимков")
        
        return jsonify({
            'success': True,
            'tile_url': tile_url,
            'image_count': image_count,
            'layer_info': {
                'type': layer_type,
                'description': config['description']
            }
        })
        
    except Exception as e:
        error_msg = f"❌ Ошибка: {str(e)}"
        print(error_msg)
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy', 
        'service': 'KrusGis Sentinel API',
        'gee_initialized': ee.data._initialized,
        'timestamp': datetime.now().isoformat()
    })

# Инициализируем Earth Engine при старте приложения
if initialize_earth_engine():
    print("✅ Приложение готово к работе")
else:
    print("❌ Приложение не может работать без Earth Engine")

if __name__ == "__main__":
    print("🚀 Запуск KrusGis Sentinel API...")
    app.run(
        host='0.0.0.0', 
        port=int(os.environ.get("PORT", 5000)), 
        debug=DEBUG
    )
