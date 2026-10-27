import sys  
import time  
from pathlib import Path

# Agregar la raíz al path para poder importar el runner del Hito 6  
sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.manim_runner import ejecutar_manim

SHOWCASES = [  
    {  
        "ruta": "videos_generados/showcase_01_geoalgebra/escena.py",  
        "clase": "ShowcaseGeoAlgebra"  
    },  
    {  
        "ruta": "videos_generados/showcase_02_ia_zoom/escena.py",  
        "clase": "ShowcaseIAZoom"  
    }  
]

def correr_showcase_completo():  
    print("🚀 INICIANDO BATERÍA DE PRUEBAS SHOWCASE (END-TO-END)")  
    print("-" * 50)  
      
    tiempo_inicio = time.time()  
    exitos = 0  
      
    for video in SHOWCASES:
        print(f"\n🎬 Compilando: {video['clase']}...")
        print(f"📁 Ruta: {video['ruta']}")

        # Llama a nuestro propio Sandbox Runner
        resultado = ejecutar_manim(video['ruta'], video['clase'], calidad="borrador")

        if resultado:
            exitos += 1
        else:
            print(f"💥 FALLO CRÍTICO EN: {video['clase']}. Revisa {resultado.reporte_error}")
            sys.exit(1) # Si uno falla, abortamos la batería de estrés
              
    tiempo_fin = time.time()  
      
    print("\n" + "=" * 50)  
    print("🏆 SHOWCASE COMPLETADO CON ÉXITO")  
    print(f"✅ Videos renderizados: {exitos}/{len(SHOWCASES)}")  
    print(f"⏱️ Tiempo total de compilación: {round(tiempo_fin - tiempo_inicio, 2)} segundos")  
    print("=" * 50)

if __name__ == "__main__":  
    correr_showcase_completo()
