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
from reportlab.lib.pagesizes import letter
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
    def _dibujar_ticket(cls, ruta, p):
        ancho_pagina, alto_pagina = letter  # 612 x 792 puntos
        margen_izq = 34
        ancho = ancho_pagina - 2 * margen_izq  # 544 pt, similar al JRXML
        c = canvas.Canvas(str(ruta), pagesize=letter, pageCompression=1)
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
        x_valor = x0 + 113
        x_col2 = x0 + 306
        x_col2_valor = x0 + 385

        # Encabezado
        texto(ancho_pagina / 2, 43, cls._texto(p, "empresa") or "MINERA MH S.A.C.", 13, True, "center")
        texto(ancho_pagina / 2, 63, cls._texto(p, "titulo") or "TICKET DE PESAJE", 12, True, "center")
        direccion = cls._texto(p, "direccion")
        if direccion:
            texto(ancho_pagina / 2, 77, direccion, 7.5, False, "center")
        linea(86, grosor=1.1)

        # Primera fila: placa y carreta.
        texto(x0, 101, "PLACA :", 10)
        texto(x_valor, 101, cls._texto(p, "placa"), 10)
        texto(x_col2, 101, "CARRETA :", 10)
        texto(x_col2_valor, 101, cls._texto(p, "carreta"), 10)

        # Lote destacado.
        texto(x0, 119, "LOTE :", 10, True)
        texto(x_valor, 119, cls._texto(p, "lote"), 11, True)

        filas = [
            ("CHOFER :", "chofer", "N° LIC. :", "licencia"),
            ("TRANSPORTISTA :", "transportista", "RUC/DNI :", "transportista_ruc"),
            ("PROVEEDOR :", "proveedor", "RUC/DNI :", "proveedor_ruc"),
            ("CONCESION :", "concesion", "CODIGO :", "codigo"),
        ]
        y = 137
        for etiqueta1, clave1, etiqueta2, clave2 in filas:
            texto(x0, y, etiqueta1, 9)
            valor1 = cls._texto(p, clave1)
            # Evita que nombres largos invadan la segunda columna.
            if len(valor1) > 29:
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
            texto(x_valor, y, lineas_obs[0], 8.5)
            for extra in lineas_obs[1:3]:
                y += 11
                texto(x_valor, y, extra, 8.5)
        y += 18
        linea(y, grosor=1.1)
        y += 22

        advertencia = cls._texto(p, "advertencia")
        if advertencia:
            texto(ancho_pagina / 2, y, advertencia, 9, True, "center", colors.HexColor("#B45000"))
            y += 18

        # Fechas y horas de ambas pesadas.
        texto(x0, y, "PRIMERA PESADA :", 9, True)
        texto(x0 + 119, y, f"{cls._texto(p, 'fecha1')}   {cls._formatear_hora(p.get('hora1'))}", 8.5)
        texto(x_col2, y, "SEGUNDA PESADA :", 9, True)
        texto(x0 + 430, y, f"{cls._texto(p, 'fecha2')} {cls._formatear_hora(p.get('hora2'))}", 7.2)
        y += 22

        # Pesos bruto y tara.
        texto(x0, y, "P. BRUTO :", 11, True)
        texto(x0 + 198, y, f"{cls._formatear_peso(p.get('peso_bruto'))} kg", 11, True, "right")
        texto(x_col2, y, "P. TARA :", 11, True)
        texto(x_fin - 12, y, f"{cls._formatear_peso(p.get('peso_tara'))} kg", 11, True, "right")
        y += 25
        linea(y, grosor=1.1)
        y += 31

        # Peso neto destacado, alineado a la derecha.
        texto(x0 + 292, y, "PESO NETO :", 13, True)
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
