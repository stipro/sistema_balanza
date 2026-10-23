"""Generación de tickets PDF directamente con Python y ReportLab.



No utiliza Java, JasperReports, JAR ni plantillas JRXML.

"""



import os

import re

import sys

from datetime import datetime

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from pathlib import Path



from reportlab.lib import colors

from reportlab.lib.pagesizes import A4, landscape

from reportlab.lib.utils import simpleSplit

from reportlab.pdfgen import canvas





class ReportePdfService:

    """Crea un ticket PDF de un lote previamente validado por PesajeService."""



    @staticmethod

    def _raiz_salida():

        """Devuelve una carpeta persistente junto al proyecto o al EXE."""

        if getattr(sys, "frozen", False):

            return Path(sys.executable).resolve().parent

        return Path(__file__).resolve().parent.parent



    @staticmethod

    def _texto(parametros, clave):

        valor = parametros.get(clave)

        return "" if valor is None else str(valor).strip()



    @staticmethod

    def _limpiar_nombre(valor):

        valor = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(valor or "").strip())

        return valor.strip("._") or "sin_dato"



    @staticmethod

    def _formatear_hora(valor):

        """Convierte una hora de 24 horas a formato de 12 horas AM/PM."""

        texto = str(valor or "").strip()

        if not texto:

            return ""



        for formato in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):

            try:

                return datetime.strptime(texto.upper(), formato).strftime("%I:%M %p")

            except ValueError:

                continue



        # Si la hora viene en un formato inesperado, no ocultamos el dato.

        return texto



    @staticmethod

    def _formatear_peso(valor, separador_decimal="."):

        """Formatea un peso con tres decimales y separador configurable."""

        if valor is None or str(valor).strip() == "":

            return ""

        try:

            numero = Decimal(str(valor).strip().replace(",", "."))

            numero = numero.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

            resultado = f"{numero:.3f}"

            if separador_decimal != ".":

                resultado = resultado.replace(".", separador_decimal)

            return resultado

        except (InvalidOperation, ValueError):

            return str(valor).strip()



    @classmethod

    def generar_ticket(cls, parametros):

        """Genera y abre un PDF para un solo lote.



        El Service de negocio debe validar previamente que el lote esté

        COMPLETADO y contenga peso bruto, tara, neto y fechas.

        """

        if not isinstance(parametros, dict):

            raise TypeError("Los datos del ticket deben enviarse como un diccionario.")



        requeridos = ("lote", "peso_bruto", "peso_tara", "peso_neto", "fecha1", "fecha2")

        faltantes = [campo for campo in requeridos if not cls._texto(parametros, campo)]

        if faltantes:

            raise ValueError(

                "No se puede generar el ticket porque faltan datos: "

                + ", ".join(faltantes)

            )



        raiz = cls._raiz_salida()

        salida_dir = raiz / "reportes_generados"

        salida_dir.mkdir(parents=True, exist_ok=True)



        lote = cls._limpiar_nombre(cls._texto(parametros, "lote"))

        ticket = cls._limpiar_nombre(cls._texto(parametros, "ticket") or "sin_ticket")

        marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        salida = salida_dir / f"ticket_{ticket}_{lote}_{marca_tiempo}.pdf"



        cls._dibujar_ticket(salida, parametros)



        if not salida.is_file() or salida.stat().st_size < 500:

            raise RuntimeError("No se pudo crear un archivo PDF válido.")



        # Abrir el PDF con el visor predeterminado en Windows.

        if sys.platform.startswith("win"):

            os.startfile(str(salida))



        return str(salida)



    @classmethod
    def generar_declaracion_jurada(cls, datos):
        """Genera la DJ por proveedor siguiendo la composición del JRXML."""
        if not isinstance(datos, dict) or not datos.get("lotes"):
            raise ValueError("No hay lotes para generar la declaración jurada.")

        salida_dir = cls._raiz_salida() / "reportes_generados"
        salida_dir.mkdir(parents=True, exist_ok=True)
        proveedor = cls._limpiar_nombre(datos.get("proveedor"))
        ticket = cls._limpiar_nombre(datos.get("ticket") or "sin_ticket")
        marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        salida = salida_dir / f"DJ_traslado_{ticket}_{proveedor}_{marca}.pdf"

        ancho, alto = A4
        canvas_pdf = canvas.Canvas(str(salida), pagesize=A4, pageCompression=1)
        canvas_pdf.setTitle(f"DJ de traslado de mineral - {datos.get('proveedor', '')}")
        canvas_pdf.setAuthor("MINERA MH S.A.C.")

        def valor(clave):
            return str(datos.get(clave) or "").strip()

        def texto(x, y_superior, contenido, tam=10, negrita=False):
            canvas_pdf.setFont("Helvetica-Bold" if negrita else "Helvetica", tam)
            canvas_pdf.setFillColor(colors.black)
            canvas_pdf.drawString(x, alto-y_superior-11, str(contenido or ""))

        def campo(x, y, ancho_campo, alto_campo, contenido, tam=10, negrita=True):
            """Valor centrado y línea punteada como los text fields del JRXML."""
            contenido = str(contenido or "")
            fuente = "Helvetica-Bold" if negrita else "Helvetica"
            tam_ajustado = tam
            while contenido and tam_ajustado > 6 and canvas_pdf.stringWidth(
                contenido, fuente, tam_ajustado
            ) > ancho_campo-4:
                tam_ajustado -= 0.25
            canvas_pdf.setFont(fuente, tam_ajustado)
            canvas_pdf.drawCentredString(
                x+ancho_campo/2, alto-y-alto_campo+4, contenido
            )
            canvas_pdf.saveState()
            canvas_pdf.setStrokeColor(colors.HexColor("#808080"))
            canvas_pdf.setLineWidth(0.5)
            canvas_pdf.setDash(1, 1)
            canvas_pdf.line(x, alto-y-alto_campo, x+ancho_campo, alto-y-alto_campo)
            canvas_pdf.restoreState()

        def parrafo(contenido, x, y, ancho_parrafo=460, tam=10, interlineado=16):
            lineas = simpleSplit(contenido, "Helvetica", tam, ancho_parrafo)
            canvas_pdf.setFont("Helvetica", tam)
            for linea_texto in lineas:
                canvas_pdf.drawString(x, alto-y-10, linea_texto)
                y += interlineado
            return y

        # Título, campos y posiciones siguen la composición de dj_traslado_mineral.jrxml.
        canvas_pdf.setFont("Helvetica-Bold", 14)
        titulo = "DECLARACION JURADA DE TRASLADO DE MINERAL"
        canvas_pdf.drawCentredString(ancho/2, alto-88, titulo)
        ancho_titulo = canvas_pdf.stringWidth(titulo, "Helvetica-Bold", 14)
        canvas_pdf.setLineWidth(0.6)
        canvas_pdf.line((ancho-ancho_titulo)/2, alto-95,
                        (ancho+ancho_titulo)/2, alto-95)

        texto(68, 109, "Yo,")
        campo(110, 109, 300, 16, valor("chofer"))
        texto(412, 109, ", con Documento Nacional")
        texto(68, 127, "de Identidad")
        campo(151, 127, 76, 16, valor("dni_chofer"))
        texto(230, 127, "con N° de Licencia de Conducir")
        campo(381, 127, 70, 16, valor("brevete"))
        texto(462, 127, ", con domicilio")
        texto(68, 146, "en")
        campo(94, 146, 403, 16, valor("domicilio_dni"))

        texto(68, 166, "conductor del vehículo de placa")
        campo(230, 166, 137, 16, valor("vehiculo_placas"))
        texto(366, 166, ", en representación del transportista")
        texto(68, 184, ",")
        campo(87, 184, 284, 16, valor("transportista"))
        texto(376, 184, ", DECLARO BAJO JURAMENTO")
        texto(68, 201, "haber trasladado la cantidad de")
        campo(230, 201, 60, 16, cls._formatear_peso(datos.get("total_tmh")))
        texto(362, 201, "TMH de mineral aurífero sin procesar")
        texto(68, 219, "desde la CONCESION:")
        campo(171, 219, 128, 16, valor("concesion"), tam=9)
        texto(304, 219, ", CODIGO")
        campo(370, 219, 83, 16, valor("codigo_concesion"))
        texto(461, 219, ", UBICACION:")
        campo(68, 236, 462, 16, valor("procedencia"))

        texto(68, 253,
              ", ubicada en el Bosque JS Sector Pampa la Aguada, distrito de Chala, provincia de Caraveli,")
        texto(68, 271, "departamento de Arequipa. El mineral es de propiedad de")
        campo(336, 271, 178, 16, valor("proveedor"), tam=9)
        texto(520, 271, ",")
        texto(68, 290, "con RUC")
        campo(126, 290, 74, 16, valor("proveedor_ruc"))
        texto(209, 290, ". Con Guia de Remision Remitente N°")
        campo(398, 290, 82, 16, valor("guias_proveedor"), tam=9)
        texto(486, 290, ".")

        legal_1 = (
            "Formulo la presente Declaración para los fines pertinentes respecto al sustento de traslado "
            "de mineral, teniendo la presente carácter de Declaración Jurada, asumiendo en caso de "
            "comprobarse falsedad las consecuencias penales y civiles, liberando a Minera MH SAC., "
            "de toda responsabilidad civil, penal o administrativa."
        )
        parrafo(legal_1, 68, 324, ancho_parrafo=462, tam=10, interlineado=16)
        legal_2 = (
            "Para mayor constancia y validez y en cumplimiento firmo y pongo mi huella digital al pie "
            "del presente documento, para los fines legales correspondientes."
        )
        parrafo(legal_2, 68, 411, ancho_parrafo=462, tam=10, interlineado=16)

        fecha = datos.get("fecha_emision")
        if isinstance(fecha, datetime):
            fecha_dt = fecha
        else:
            try:
                fecha_dt = datetime.fromisoformat(str(fecha or "").replace("Z", "+00:00"))
            except ValueError:
                fecha_dt = datetime.now()
        meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        texto(262, 460, valor("lugar") or "CHALA")
        texto(362, 460, ";")
        fecha_texto = valor("fecha") or (
            f"{fecha_dt.day} de {meses[fecha_dt.month-1]} de {fecha_dt.year}"
        )
        campo(380, 460, 135, 16, fecha_texto, tam=10, negrita=False)

        texto(68, 501, "Apellidos y Nombres:")
        campo(179, 501, 192, 16, valor("chofer"), tam=10, negrita=False)
        texto(68, 526, "DNI N°:")
        campo(179, 526, 192, 16, valor("dni_chofer"), tam=10, negrita=False)
        canvas_pdf.setStrokeColor(colors.black)
        canvas_pdf.setLineWidth(0.75)
        canvas_pdf.rect(428, alto-540-89, 74, 89, fill=0, stroke=1)
        canvas_pdf.saveState()
        canvas_pdf.setStrokeColor(colors.HexColor("#808080"))
        canvas_pdf.setLineWidth(0.5)
        canvas_pdf.setDash(1, 1)
        canvas_pdf.line(156, alto-629, 276, alto-629)
        canvas_pdf.restoreState()
        canvas_pdf.setFont("Helvetica", 10)
        canvas_pdf.drawCentredString(216, alto-645, "Firma")
        canvas_pdf.setFont("Helvetica", 8)
        canvas_pdf.drawCentredString(465, alto-643, "Huella")

        canvas_pdf.save()
        if not salida.is_file() or salida.stat().st_size < 500:
            raise RuntimeError("No se pudo crear un PDF válido de la declaración jurada.")
        if sys.platform.startswith("win"):
            os.startfile(str(salida))
        return str(salida)

    def _dibujar_ticket(cls, ruta, p):

        ancho_pagina, alto_pagina = A4    # 612 x 792 puntos

        margen_izq = 18

        ancho = ancho_pagina - 2 * margen_izq  # 544 pt, similar al JRXML

        c = canvas.Canvas(str(ruta), pagesize = A4, pageCompression=1)

        c.setTitle(f"Ticket de pesaje - Lote {cls._texto(p, 'lote')}")

        c.setAuthor("MINERA MH S.A.C.")

        c.setSubject("Ticket de pesaje por lote")



        # Coordenadas desde la parte superior de la hoja.

        def y_arriba(y):

            return alto_pagina - y



        def texto(x, y, contenido, tam=9, negrita=False, alineacion="left", color=colors.black):

            contenido = "" if contenido is None else str(contenido)

            c.setFillColor(color)

            c.setFont("Helvetica-Bold" if negrita else "Helvetica", tam)

            yy = y_arriba(y)

            if alineacion == "center":

                c.drawCentredString(x, yy, contenido)

            elif alineacion == "right":

                c.drawRightString(x, yy, contenido)

            else:

                c.drawString(x, yy, contenido)



        def linea(y, x1=margen_izq, x2=margen_izq + ancho, grosor=0.8):

            c.setStrokeColor(colors.black)

            c.setLineWidth(grosor)

            c.line(x1, y_arriba(y), x2, y_arriba(y))



        x0 = margen_izq

        x_fin = x0 + ancho

        x_valor = x0 + 100

        x_col2 = x0 + 400

        x_col2_valor = x0 + 445



        # Encabezado
        texto(ancho_pagina / 2, 28, cls._texto(p, "empresa") or "MINERA MH S.A.C.", 13, True, "center")
        texto(ancho_pagina / 2, 48, cls._texto(p, "titulo") or "TICKET DE PESAJE", 12, True, "center")

        direccion = cls._texto(p, "direccion")
        if direccion:texto(ancho_pagina / 2, 62, direccion, 7.5, False, "center")
        linea(71, grosor=1.1)

        # Primera fila: placa y carreta.

        texto(x0, 83, "PLACA :", 10)

        texto(x_valor, 83, cls._texto(p, "placa"), 10)

        texto(230, 83, "CARRETA :", 10)

        texto(200, 83, cls._texto(p, "carreta"), 10)



        # Lote destacado.

        texto(395, 83, "LOTE :", 10, True)

        texto(440, 83, cls._texto(p, "lote"), 11, True)



        filas = [

            ("CHOFER :", "chofer", "N° LIC. :", "licencia"),

            ("TRANSPORTISTA :", "transportista", "RUC/DNI :", "transportista_ruc"),

            ("PROVEEDOR :", "proveedor", "RUC/DNI :", "proveedor_ruc"),

            ("CONCESION :", "concesion", "CODIGO :", "codigo"),

        ]

        y = 101

        for etiqueta1, clave1, etiqueta2, clave2 in filas:

            texto(x0, y, etiqueta1, 9)

            valor1 = cls._texto(p, clave1)

            # Evita que nombres largos invadan la segunda columna.

            if len(valor1) > 35:

                valor1 = valor1[:26] + "..."

            texto(x_valor, y, valor1, 8.5)

            texto(x_col2, y, etiqueta2, 9)

            texto(x_col2_valor, y, cls._texto(p, clave2)[:22], 8.5)

            y += 18



        texto(x0, y, "PROCEDENCIA :", 9)

        texto(x_valor, y, cls._texto(p, "procedencia")[:70], 8.5)

        y += 18

        texto(x0, y, "PRODUCTO :", 9)

        texto(x_valor, y, cls._texto(p, "producto")[:70], 8.5)

        y += 18

        texto(x0, y, "N° DE SACOS :", 9)

        texto(x_valor, y, cls._texto(p, "n_sacos"), 11, True)

        y += 18

        texto(x0, y, "N° G.R. REMIT. :", 9)

        texto(x_valor, y, cls._texto(p, "gr_remit")[:28], 8.5)

        texto(x_col2, y, "N° G.R. TRANSP. :", 9)

        texto(x0 + 414, y, cls._texto(p, "gr_transp")[:20], 8.5)

        y += 18



        # Observación, con ajuste a varias líneas cuando sea necesario.

        texto(x0, y, "OBSERVACION :", 9)

        observacion = cls._texto(p, "observacion")

        lineas_obs = simpleSplit(observacion, "Helvetica", 8.5, ancho - 120) if observacion else []

        if lineas_obs:

            texto(x_valor, y, lineas_obs[0], 10)

            for extra in lineas_obs[1:3]:

                y += 11

                texto(x_valor, y, extra, 10)

        y += 8

        linea(y, grosor=1.1)

        y += 15



        advertencia = cls._texto(p, "advertencia")

        if advertencia:

            texto(ancho_pagina / 2, y, advertencia, 9, True, "center", colors.HexColor("#B45000"))

            y += 18



        # Fechas y horas de ambas pesadas.

        texto(x0, y, "PRIMERA PESADA :", 11, True)

        texto(x0 + 119, y, f"{cls._texto(p, 'fecha1')}   {cls._formatear_hora(p.get('hora1'))}", 10)

        texto(300, y, "SEGUNDA PESADA :", 11, True)

        texto(470, y, f"{cls._texto(p, 'fecha2')} {cls._formatear_hora(p.get('hora2'))}", 10)

        y += 22



        # Pesos bruto y tara.

        texto(x0, y, "P. BRUTO :", 11, True)

        texto(x0 + 198, y, f"{cls._formatear_peso(p.get('peso_bruto'))} kg", 11, True, "right")

        texto(350, y, "P. TARA :", 11, True)

        texto(500, y, f"{cls._formatear_peso(p.get('peso_tara'))} kg", 11, True, "right")

        y += 8

        linea(y, grosor=1.1)

        y += 30



        # Peso neto destacado, alineado a la derecha.

        texto(x0 + 308, y, "PESO NETO :", 13, True)

        texto(x_fin - 43, y, cls._formatear_peso(p.get("peso_neto"), separador_decimal=","), 13, True, "right")

        texto(x_fin, y, "kg", 13, True, "right")



        # Firma del operador.

        firma_y = min(y + 34, alto_pagina - 70)

        c.setStrokeColor(colors.black)

        c.setLineWidth(0.7)

        c.line(x0 + 23, y_arriba(firma_y), x0 + 193, y_arriba(firma_y))

        texto(x0 + 108, firma_y + 13, "FIRMA OPERADOR", 8.5, False, "center")



        nota_pie = cls._texto(p, "nota_pie")

        if nota_pie:

            nota_lineas = simpleSplit(nota_pie, "Helvetica-Oblique", 7, ancho)

            yy = alto_pagina - 35

            c.setFont("Helvetica-Oblique", 7)

            c.setFillColor(colors.HexColor("#646464"))

            for linea_nota in nota_lineas[:5]:

                c.drawString(x0, yy, linea_nota)

                yy -= 9



        c.showPage()

        c.save()
