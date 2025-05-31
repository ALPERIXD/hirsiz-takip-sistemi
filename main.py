import streamlit as st
import json
import os
import pickle
from typing import List, Dict, Any
import math

import folium
from streamlit_folium import st_folium
import osmnx as ox
import networkx as nx

DATA_FILE = "kamera_data.json"
GRAPH_CACHE_FILE = "bolu_graph_cache.pkl"

@st.cache_data(show_spinner=False)
def load_road_network():
    """Bolu merkez için yol ağını yükler - önce cache'den kontrol eder"""

    # Önce cache dosyasını kontrol et
    if os.path.exists(GRAPH_CACHE_FILE):
        try:
            with open(GRAPH_CACHE_FILE, 'rb') as f:
                graph = pickle.load(f)
            st.success("✅ Yol ağı cache'den yüklendi!")
            return graph
        except Exception as e:
            st.warning(f"Cache dosyası okunamadı, yeniden indiriliyor... ({e})")

    # Cache yoksa veya bozuksa internetten çek
    st.info("🌐 Yol ağı verileri internetten indiriliyor... (İlk seferlik)")

    # Çok küçük alan - sadece Bolu merkez (1km x 1km)
    north, south, east, west = 40.7450, 40.7350, 31.6100, 31.5950
    try:
        graph = ox.graph_from_bbox(bbox=(north, south, east, west), network_type='drive')

        # Cache'e kaydet
        try:
            with open(GRAPH_CACHE_FILE, 'wb') as f:
                pickle.dump(graph, f)
            st.success("✅ Yol ağı cache'e kaydedildi!")
        except Exception as e:
            st.warning(f"Cache kaydedilemedi: {e}")

        return graph
    except Exception as e:
        st.error(f"Yol ağı yüklenirken hata: {e}")
        return None

def load_camera_data() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data if isinstance(data, list) else []
        else:
            return []
    except Exception as e:
        st.error(f"Veri dosyası okunurken hata oluştu: {e}")
        return []

def save_camera_data(cameras: List[Dict[str, Any]]) -> bool:
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as file:
            json.dump(cameras, file, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"Veri kaydedilirken hata oluştu: {e}")
        return False

def add_new_camera(name: str, x: float, y: float, node_id, cameras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    new_camera = {
        "name": name,
        "x": x,
        "y": y,
        "node_id": node_id
    }
    cameras.append(new_camera)
    return cameras

def find_nearest_node(graph, lat, lon):
    """Verilen koordinatlara en yakın yol düğümünü bulur"""
    if graph is None:
        return None
    try:
        return ox.distance.nearest_nodes(graph, lon, lat)
    except Exception as e:
        st.error(f"En yakın düğüm bulunamadı: {e}")
        return None

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """İki nokta arasındaki mesafeyi hesaplar (kilometre)"""
    R = 6371  # Dünya yarıçapı km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def calculate_route(graph, start_node, end_node):
    """İki düğüm arasında en kısa yolu hesaplar"""
    if graph is None or start_node is None or end_node is None:
        return None
    try:
        route = nx.shortest_path(graph, start_node, end_node, weight='length')
        return route
    except Exception as e:
        st.error(f"Rota hesaplanamadı: {e}")
        return None

def find_cameras_on_route(graph, route_nodes, cameras, buffer_distance=0.1):
    """Rota üzerindeki veya yakınındaki kameraları bulur"""
    if not route_nodes or not cameras:
        return []

    route_cameras = []

    for camera in cameras:
        camera_node = camera.get('node_id')
        if camera_node in route_nodes:
            # Kamera doğrudan rota üzerinde
            route_cameras.append({
                **camera,
                "on_route": True,
                "distance_to_route": 0
            })
        else:
            # Kameranın rotaya yakınlığını kontrol et
            min_distance = float('inf')
            for route_node in route_nodes:
                if graph.has_node(route_node) and graph.has_node(camera_node):
                    try:
                        # İki düğüm arasındaki koordinat farkını hesapla
                        route_coord = (graph.nodes[route_node]['y'], graph.nodes[route_node]['x'])
                        camera_coord = (graph.nodes[camera_node]['y'], graph.nodes[camera_node]['x'])
                        distance = calculate_distance(route_coord[0], route_coord[1], 
                                                    camera_coord[0], camera_coord[1])
                        min_distance = min(min_distance, distance)
                    except:
                        continue

            if min_distance <= buffer_distance:
                route_cameras.append({
                    **camera,
                    "on_route": False,
                    "distance_to_route": min_distance
                })

    # Rota üzerindeki kameraları önce, sonra yakın olanları mesafeye göre sırala
    route_cameras.sort(key=lambda x: (not x['on_route'], x['distance_to_route']))
    return route_cameras

def create_route_map(graph, route_nodes, cameras, start_camera, end_camera):
    """Rota ve kameraları gösteren harita oluşturur"""
    if not route_nodes or graph is None:
        return None

    # Harita merkezi hesapla
    route_coords = []
    for node in route_nodes:
        if graph.has_node(node):
            route_coords.append([graph.nodes[node]['y'], graph.nodes[node]['x']])

    if not route_coords:
        return None

    center_lat = sum(coord[0] for coord in route_coords) / len(route_coords)
    center_lon = sum(coord[1] for coord in route_coords) / len(route_coords)

    # Haritayı oluştur
    route_map = folium.Map(location=[center_lat, center_lon], zoom_start=15)

    # Rotayı çiz
    folium.PolyLine(
        locations=route_coords,
        color='red',
        weight=5,
        opacity=0.8,
        popup='Hırsız Güzergahı'
    ).add_to(route_map)

    # Başlangıç kamerasını yeşil ile işaretle
    folium.Marker(
        location=[start_camera['y'], start_camera['x']],
        popup=f"BAŞLANGIÇ: {start_camera['name']}",
        icon=folium.Icon(color="green", icon="play", prefix="fa")
    ).add_to(route_map)

    # Bitiş kamerasını kırmızı ile işaretle
    folium.Marker(
        location=[end_camera['y'], end_camera['x']],
        popup=f"BİTİŞ: {end_camera['name']}",
        icon=folium.Icon(color="red", icon="stop", prefix="fa")
    ).add_to(route_map)

    # Diğer kameraları mavi ile işaretle
    for camera in cameras:
        if camera['name'] not in [start_camera['name'], end_camera['name']]:
            folium.Marker(
                location=[camera['y'], camera['x']],
                popup=camera['name'],
                icon=folium.Icon(color="blue", icon="camera", prefix="fa")
            ).add_to(route_map)

    return route_map

def clear_cache():
    """Cache dosyalarını temizler"""
    try:
        if os.path.exists(GRAPH_CACHE_FILE):
            os.remove(GRAPH_CACHE_FILE)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Cache temizlenirken hata: {e}")
        return False

def main():
    st.set_page_config(page_title="Hırsız Takip Sistemi", layout="wide")
    st.title("🕵️ Hırsız Takip Sistemi")
    st.markdown("---")
    st.markdown("Bu sistem ile kamera konumlarını belirleyip, hırsızın geçtiği güzergahı analiz edebilirsiniz.")

    # Sidebar'a cache kontrolleri ekle
    with st.sidebar:
        st.header("⚙️ Sistem Ayarları")

        # Cache durumunu göster
        if os.path.exists(GRAPH_CACHE_FILE):
            file_size = os.path.getsize(GRAPH_CACHE_FILE) / 1024  # KB
            st.success(f"✅ Yol ağı cache'i mevcut ({file_size:.1f} KB)")
        else:
            st.info("📂 Cache henüz oluşturulmamış")

        if st.button("🔄 Cache'i Yenile"):
            if clear_cache():
                st.success("Cache temizlendi, sayfa yeniden yüklenecek...")
                st.rerun()

        st.markdown("---")
        st.caption("💡 İlk açılışta yol ağı indirilir ve cache'lenir. Sonraki açılışlar çok daha hızlı olur.")

    # Yol ağını yükle (artık çok daha hızlı!)
    graph = load_road_network()

    if graph is None:
        st.error("Yol ağı yüklenemedi. Lütfen daha sonra tekrar deneyin.")
        return

    if 'cameras' not in st.session_state:
        st.session_state.cameras = load_camera_data()
        if st.session_state.cameras:
            st.success(f"✅ {len(st.session_state.cameras)} adet kayıtlı kamera yüklendi.")

    # İki sütun layout
    col1, col2 = st.columns([1, 1])

    with col1:
        st.header("📝 Yeni Kamera Ekle")

        # Kamera ekleme haritası
        default_location = [40.7400, 31.6025]  # Bolu merkez
        harita = folium.Map(location=default_location, zoom_start=15)

        for cam in st.session_state.cameras:
            folium.Marker(
                location=[cam['y'], cam['x']],
                popup=f"{cam['name']}",
                icon=folium.Icon(color="blue", icon="camera", prefix="fa")
            ).add_to(harita)

        folium.LatLngPopup().add_to(harita)
        clicked_data = st_folium(harita, width=500, height=400)

        if clicked_data and clicked_data.get("last_clicked"):
            x = clicked_data["last_clicked"]["lng"]
            y = clicked_data["last_clicked"]["lat"]

            camera_name = st.text_input("Kamera Adı", placeholder="Örn: Merkez Kavşağı Kamerası")

            if st.button("🎯 Kamerayı Kaydet"):
                if not camera_name.strip():
                    st.error("⚠️ Kamera adı boş olamaz.")
                else:
                    existing_names = [cam['name'] for cam in st.session_state.cameras]
                    if camera_name.strip() in existing_names:
                        st.error("⚠️ Bu isimde bir kamera zaten kayıtlı!")
                    else:
                        # En yakın yol düğümünü bul
                        node_id = find_nearest_node(graph, y, x)
                        if node_id is not None:
                            st.session_state.cameras = add_new_camera(camera_name.strip(), x, y, node_id, st.session_state.cameras)
                            if save_camera_data(st.session_state.cameras):
                                st.success(f"✅ '{camera_name}' başarıyla kaydedildi!")
                                st.rerun()
                            else:
                                st.error("❌ Kamera kaydedilirken bir hata oluştu!")
                        else:
                            st.error("❌ Bu konum için yol ağı düğümü bulunamadı!")
        else:
            st.info("📍 Konum seçmek için haritaya tıklayın.")

    with col2:
        st.header("🔍 Güzergah Analizi")

        if len(st.session_state.cameras) >= 2:
            # Başlangıç ve bitiş kamerası seçimi
            start_camera_name = st.selectbox("Başlangıç Kamerası (Hırsızın İlk Görüldüğü Yer)", 
                                           [cam['name'] for cam in st.session_state.cameras])
            end_camera_name = st.selectbox("Bitiş Kamerası (Hırsızın Son Görüldüğü Yer)", 
                                         [cam['name'] for cam in st.session_state.cameras])

            if start_camera_name != end_camera_name:
                start_camera = next((cam for cam in st.session_state.cameras if cam['name'] == start_camera_name), None)
                end_camera = next((cam for cam in st.session_state.cameras if cam['name'] == end_camera_name), None)

                if st.button("🗺️ Güzergahı Hesapla"):
                    if start_camera and end_camera:
                        start_node = start_camera.get('node_id')
                        end_node = end_camera.get('node_id')

                        if start_node and end_node:
                            with st.spinner("Güzergah hesaplanıyor..."):
                                route_nodes = calculate_route(graph, start_node, end_node)

                            if route_nodes:
                                st.success(f"✅ Güzergah bulundu! {len(route_nodes)} düğümden oluşuyor.")

                                # Rota haritasını oluştur ve göster
                                route_map = create_route_map(graph, route_nodes, st.session_state.cameras, 
                                                           start_camera, end_camera)
                                if route_map:
                                    st.markdown("### 🗺️ Hırsız Güzergahı")
                                    st_folium(route_map, width=500, height=400)

                                # Rota üzerindeki kameraları bul
                                route_cameras = find_cameras_on_route(graph, route_nodes, st.session_state.cameras)

                                if route_cameras:
                                    st.markdown("### 📷 Güzergah Üzerindeki Kameralar")
                                    for i, cam in enumerate(route_cameras, 1):
                                        status = "🎯 Rota üzerinde" if cam['on_route'] else f"📍 {cam['distance_to_route']:.2f} km yakınında"
                                        st.write(f"{i}. **{cam['name']}** - {status}")
                                else:
                                    st.info("Bu güzergah üzerinde başka kamera bulunamadı.")
                            else:
                                st.error("❌ Bu iki kamera arasında güzergah bulunamadı!")
                        else:
                            st.error("❌ Seçilen kameraların yol ağı bilgileri eksik!")
            else:
                st.warning("⚠️ Başlangıç ve bitiş kameraları farklı olmalı!")
        else:
            st.info("📷 Güzergah analizi için en az 2 kamera gerekli.")

    st.header("📋 Kayıtlı Kameralar")

    if st.session_state.cameras:
        st.info(f"💡 Toplam {len(st.session_state.cameras)} kamera kayıtlı")
        for i, camera in enumerate(st.session_state.cameras, 1):
            with st.container():
                col1, col2, col3, col4, col5 = st.columns([1, 3, 2, 2, 2])
                with col1:
                    st.write(f"**#{i}**")
                with col2:
                    st.write(f"📷 **{camera['name']}**")
                with col3:
                    st.write(f"**X:** {camera['x']:.5f}")
                with col4:
                    st.write(f"**Y:** {camera['y']:.5f}")
                with col5:
                    st.write(f"**Düğüm:** {camera.get('node_id', 'N/A')}")
                st.markdown("---")

        with st.expander("🔍 JSON Formatında Gör"):
            st.json(st.session_state.cameras)

        # Butonlar ve onaylar
        st.markdown("---")
        st.header("⚠️ Dikkatli Ol: Verileri Sıfırla")
        if not st.session_state.get('confirm_delete', False):
            if st.button("🗑️ Tüm Verileri Temizle"):
                st.session_state.confirm_delete = True
                st.warning("⚠️ Verileri silmek istediğine emin misin? Bu işlem geri alınamaz. Aynı butona tekrar bas.")
        else:
            if st.button("❗ Eminim, Verileri Sil"):
                st.session_state.cameras = []
                if save_camera_data([]):
                    st.success("✅ Tüm veriler silindi!")
                    st.session_state.confirm_delete = False
                    st.rerun()
                else:
                    st.error("❌ Veriler temizlenirken hata oluştu!")
            if st.button("✋ İptal Et"):
                st.session_state.confirm_delete = False
                st.info("Veri silme işlemi iptal edildi.")

    else:
        st.info("📭 Henüz kayıtlı kamera yok.")

    st.markdown("---")
    st.markdown("💾 **Veriler `kamera_data.json` dosyasında saklanır.**")
    st.markdown("🚀 **Yol ağı verileri `bolu_graph_cache.pkl` dosyasında cache'lenir.**")

if __name__ == "__main__":
    main()
