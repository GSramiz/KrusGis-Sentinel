import ee
import json
import os
import traceback
from flask import Flask, render_template, request, jsonify
from oauth2client.service_account import ServiceAccountCredentials

# Инициализация Flask
app = Flask(__name__)

# Конфигурация
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

def initialize_earth_engine():
    """Инициализация Earth Engine"""
    try:
        print("\n🔄 Инициализация Earth Engine...")
        
        service_account_info = json.loads(os.environ["GEE_CREDENTIALS"])
        
        credentials = ee.ServiceAccountCredentials(
            service_account_info["client_email"],
            key_data=json.dumps(service_account_info)
        )
        ee.Initialize(credentials)
        print("✅ Earth Engine инициализирован")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка инициализации Earth Engine: {str(e)}")
        return False

def mask_clouds(img):
    """Маскировка облаков - сохраняем твою логику"""
    scl = img.select("SCL")
    allowed = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
    return img.updateMask(allowed).resample("bilinear")

@app.route('/')
def index():
    """Главная страница с картой"""
    return render_template('index.html')

@app.route('/api/get_sentinel_image', methods=['POST'])
def get_sentinel_image():
    """API для получения спутникового снимка"""
    try:
        # Получаем параметры из запроса
        data = request.json
        geometry = ee.Geometry.Rectangle(data['bounds'])
        start_date = data['start_date']
        end_date = data['end_date']
        cloud_filter = data.get('cloud_filter', 30)
        enable_smoothing = data.get('smoothing', True)
        
        print(f"📡 Запрос снимка: {start_date} - {end_date}, облачность < {cloud_filter}%")
        
        # Формируем коллекцию снимков
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_date, end_date)
            .filterBounds(geometry)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_filter))
        )
        
        # Применяем маскировку облаков если включено сглаживание
        if enable_smoothing:
            collection = collection.map(mask_clouds)
        
        # Создаем мозаику
        mosaic = collection.median()
        
        # Получаем URL для тайлов
        tile_info = ee.data.getMapId({
            "image": mosaic,
            "bands": ["B4", "B3", "B2"],  # RGB
            "min": "0,0,0",
            "max": "3000,3000,3000",
            "region": geometry
        })
        
        # Формируем URL для тайлов
        map_id = tile_info["mapid"]
        tile_url = f"https://earthengine.googleapis.com/v1/maps/{map_id}/tiles/{{z}}/{{x}}/{{y}}"
        
        return jsonify({
            'success': True,
            'tile_url': tile_url,
            'image_count': collection.size().getInfo()
        })
        
    except Exception as e:
        print(f"❌ Ошибка: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/regions')
def get_regions():
    """API для получения списка регионов (опционально)"""
    try:
        # Можно сохранить функциональность выбора регионов если нужно
        fc = ee.FeatureCollection("projects/ee-romantik1994/assets/region")
        regions = fc.aggregate_array('title').getInfo()
        return jsonify({'regions': regions})
    except Exception as e:
        return jsonify({'regions': []})

if __name__ == "__main__":
    # Инициализируем Earth Engine при запуске
    if initialize_earth_engine():
        app.run(
            host='0.0.0.0', 
            port=5000, 
            debug=DEBUG
        )
    else:
        print("❌ Не удалось запустить приложение")
