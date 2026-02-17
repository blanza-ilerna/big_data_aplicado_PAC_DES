# Guía de Uso: GitHub Codespaces

Este repositorio está optimizado para trabajar con **GitHub Codespaces**. Esto te permite disponer de un entorno de Big Data completo (Python, Docker, Flink, Grafana, etc.) directamente en tu navegador o en VS Code, sin instalaciones locales.

---

## 🚀 Inicio y Parada

### Cómo iniciar tu entorno
1. En la página del repositorio, haz clic en el botón **"Code"** (verde).
2. Selecciona la pestaña **"Codespaces"**.
3. Haz clic en **"Create codespace on main"**. 
   *GitHub configurará automáticamente el contenedor, instalará las dependencias y levantará los servicios de Docker-Compose.*

### Cómo detenerlo (IMPORTANTE)
Para no agotar tus horas gratuitas:
- **Desde VS Code:** Haz clic en el indicador azul "Codespaces" (abajo a la izquierda) y elige **"Stop Current Codespace"**.
- **Desde la web:** Ve a [github.com/codespaces](https://github.com/codespaces), busca tu entorno y selecciona **"Stop Codespace"**.

### Cómo renombrar tu Codespace
Por defecto, GitHub asigna nombres aleatorios (como *fluffy-engine-x4j6*). Para organizarte mejor:
1. Entra en [github.com/codespaces](https://github.com/codespaces).
2. Haz clic en los tres puntos (`...`) del codespace que quieras cambiar.
3. Selecciona **"Rename"** y dale un nombre descriptivo (ej: "BigData-PAC-1").

---

## 💰 Cuota Gratuita (Free Tier)

GitHub ofrece una capacidad limitada pero potente para cuentas personales. Es fundamental entender cómo se consume:

### 1. Cómputo (Core-Hours)
Dispones de **120 core-hours mensuales** (horas-núcleo). El tiempo real de uso depende de la máquina que elijas:
- **Máquina de 2 núcleos:** Consume 2 core-hours por cada hora real. (Tendrás **60 horas reales** al mes).
- **Máquina de 4 núcleos:** Consume 4 core-hours por cada hora real. (Tendrás **30 horas reales** al mes).

### 2. Almacenamiento
Tienes **15 GB mensuales** gratuitos. 
> **Ojo:** Los Codespaces detenidos (aparcados) **siguen consumiendo almacenamiento**. Si dejas entornos viejos guardados, podrías agotar esta cuota rápidamente.

### Comparativa rápida
| Concepto | Plan Free (Personal) | Plan Pro (Personal) |
| :--- | :--- | :--- |
| **Cómputo** | 120 core-hours/mes | 180 core-hours/mes |
| **Almacenamiento** | 15 GB/mes | 20 GB/mes |

---

## 💡 Consejos para optimizar el consumo

1. **Ajusta el "Idle Timeout":** Ve a los ajustes de tu cuenta en GitHub (Codespaces) y configura el tiempo de suspensión automática a un valor bajo (15 o 30 minutos). Así, si te olvidas de apagarlo, la máquina se detendrá sola pronto.
2. **Borra lo que no uses:** Cuando termines una práctica, haz `push` de tus cambios y **borra** el Codespace desde el panel de gestión para liberar los GB de almacenamiento.
3. **Monitorización:** Puedes revisar tu consumo actual en los ajustes de `Billing and plans` de tu perfil de GitHub.

---

## 🔧 Resolución de Problemas

Si al entrar no ves los servicios funcionando (Grafana, Flink, etc.):
1. Abre una terminal dentro del Codespace.
2. Ejecuta: `docker compose up -d`
3. Revisa la pestaña **"Ports"** en el panel inferior para acceder a las interfaces web.
