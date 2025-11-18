import pandas as pd
from itertools import combinations
from flask import Flask, request, send_file, render_template
import io
import os

# Inicializar la aplicación Flask
app = Flask(__name__)

# --- Lógica de Procesamiento del Script Original ---

def es_cobertura_valida(monto_pago, monto_objetivo, tolerancia=1.0):
    """
    Verifica si la suma está dentro del rango permitido (±1.00) del monto objetivo.
    """
    return abs(monto_pago - monto_objetivo) <= tolerancia

def procesar_archivos_excel(df):
    """
    Ejecuta la lógica de asociación de facturas y pagos.
    Recibe el DataFrame completo y devuelve el DataFrame de resultados.
    """
    print("Iniciando procesamiento de asociación de pagos...")
    
    # Separar facturas y pagos
    facturas = df[df['CLASS'] == 'INV'].copy()
    pagos = df[df['CLASS'] == 'PMT'].copy()

    # Calcular 88% del valor de la factura
    facturas['INV_AMOUNT_88'] = facturas['INV_AMOUNT'] * 0.88

    # Inicializar lista de resultados
    resultados = []

    # Copia de pagos disponibles (se convierte a lista de diccionarios para manipulación)
    pagos_disponibles_df = pagos.copy()
    
    # Iterar sobre las facturas
    for _, factura in facturas.iterrows():
        cliente = factura['CUSTOMER_NAME']
        trx_factura = factura['TRX_NUMBER']
        valor_factura = factura['INV_AMOUNT']
        valor_88 = factura['INV_AMOUNT_88']
        
        # Filtrar pagos del mismo cliente
        pagos_cliente = pagos_disponibles_df[pagos_disponibles_df['CUSTOMER_NAME'] == cliente]
        
        # Convertir a lista de diccionarios para el manejo de combinaciones (más eficiente que iterar en DataFrames)
        pagos_lista = pagos_cliente.to_dict('records')
        
        encontrada = False
        pagos_a_eliminar = []

        # 1. Buscar coincidencia con un solo pago
        for pago in pagos_lista:
            monto_pago = pago['INV_AMOUNT']
            porcentaje = None
            
            if es_cobertura_valida(monto_pago, valor_factura):
                porcentaje = "100%"
            elif es_cobertura_valida(monto_pago, valor_88):
                porcentaje = "88%"
            
            if porcentaje:
                resultados.append({
                    'Factura_TRX': trx_factura,
                    'Cliente': cliente,
                    'ValorFactura': valor_factura,
                    'Pago_TRX': pago['TRX_NUMBER'],
                    'ValorPago': monto_pago,
                    'Porcentaje': porcentaje
                })

                pagos_a_eliminar.append(pago['TRX_NUMBER'])
                encontrada = True
                break  # Salir del loop si ya se encontró
        
        # Eliminar pagos usados antes de buscar combinaciones
        if encontrada:
            pagos_disponibles_df = pagos_disponibles_df[
                ~pagos_disponibles_df['TRX_NUMBER'].isin(pagos_a_eliminar)
            ]
            continue

        # 2. Buscar combinaciones de hasta 5 pagos
        max_r = min(6, len(pagos_lista) + 1)
        for r in range(2, max_r):
            if encontrada: break
            for combo in combinations(pagos_lista, r):
                suma = sum(p['INV_AMOUNT'] for p in combo)
                porcentaje = None
                
                if es_cobertura_valida(suma, valor_factura):
                    porcentaje = "100%"
                elif es_cobertura_valida(suma, valor_88):
                    porcentaje = "88%"
                
                if porcentaje:
                    pagos_en_combo = [p['TRX_NUMBER'] for p in combo]
                    
                    for p in combo:
                        resultados.append({
                            'Factura_TRX': trx_factura,
                            'Cliente': cliente,
                            'ValorFactura': valor_factura,
                            'Pago_TRX': p['TRX_NUMBER'],
                            'ValorPago': p['INV_AMOUNT'],
                            'Porcentaje': porcentaje
                        })
                        pagos_a_eliminar.append(p['TRX_NUMBER'])

                    encontrada = True
                    break  # Salir si se encontró combinación válida
        
        # Eliminar pagos usados
        if encontrada:
             pagos_disponibles_df = pagos_disponibles_df[
                ~pagos_disponibles_df['TRX_NUMBER'].isin(pagos_a_eliminar)
            ]

    # Crear DataFrame de resultados y devolverlo
    df_resultado = pd.DataFrame(resultados)
    return df_resultado

# --- Rutas de la Aplicación Web ---

@app.route('/')
def index():
    """Sirve la página principal de la aplicación."""
    # En una aplicación real, usarías render_template, pero como solo tengo un archivo
    # lo devolveré desde aquí. (En este caso, render_template asume que el HTML
    # está en una carpeta 'templates', pero como lo generarás también, lo pongo)
    # Sin embargo, en la práctica, Flask busca index.html. La instrucción me pide
    # generar el archivo, así que el usuario lo tendrá en el mismo entorno.
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_file():
    """
    Maneja la carga del archivo, ejecuta la lógica de negocio y devuelve el resultado.
    """
    if 'file' not in request.files:
        return {'error': 'No se encontró el archivo en la solicitud.'}, 400

    file = request.files['file']
    if file.filename == '':
        return {'error': 'No se seleccionó ningún archivo.'}, 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return {'error': 'Formato de archivo no soportado. Por favor, sube un .xlsx o .xls.'}, 400

    try:
        # Leer el archivo Excel cargado en memoria
        file_stream = io.BytesIO(file.read())
        df = pd.read_excel(file_stream)
        
        # Ejecutar la lógica de procesamiento
        df_resultado = procesar_archivos_excel(df)

        # Guardar el DataFrame de resultado en un buffer de memoria (Excel)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # Escribir el DataFrame al buffer
            df_resultado.to_excel(writer, index=False, sheet_name='Pagos_Asociados')
        
        # Mover el puntero del buffer al inicio para la lectura
        output.seek(0)
        
        # Devolver el archivo al cliente
        return send_file(
            output, 
            as_attachment=True, 
            download_name='Ageing_Pagos_Asociados.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        print(f"Error durante el procesamiento: {e}")
        return {'error': f'Ocurrió un error inesperado durante el procesamiento: {str(e)}'}, 500

# Se incluye esta línea para que Flask sepa cómo ejecutarlo, 
# aunque gunicorn (en tu Procfile) lo inicia directamente.
if __name__ == '__main__':
    app.run(debug=True)