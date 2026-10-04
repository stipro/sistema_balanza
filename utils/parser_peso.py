class ParserPeso:

    @staticmethod
    def extraer(trama):

        try:

            trama = trama.strip()

            # ==================================================
            # DEBE COMENZAR CON S
            # ==================================================

            if not trama.startswith("S"):

                return None

            # ==================================================
            # FORMATO ORIGINAL
            #
            # cadena.Substring(6, 6)
            # ==================================================

            if len(trama) >= 12:

                peso_original = (
                    trama[6:12].strip()
                )

                if peso_original:

                    peso_limpio = (
                        peso_original
                        .replace(".", "")
                        .replace("-", "")
                    )

                    if peso_limpio.isdigit():

                        return peso_original

            # ==================================================
            # FORMATO OBSERVADO
            #
            # S          0 kg
            # ==================================================

            partes = trama.split()

            if len(partes) >= 2:

                peso = partes[1].strip()

                peso_limpio = (peso.replace(".", "").replace("-", ""))

                if peso_limpio.isdigit():

                    return peso

            return None

        except Exception:

            return None