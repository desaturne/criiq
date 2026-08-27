# Running CRIIQ

You need **Docker Desktop**. Nothing else — no Python, no Node, no database.

## 1. Install Docker Desktop

https://www.docker.com/products/docker-desktop/

On Windows the installer may ask to enable **WSL 2** — say yes, and reboot if
prompted. Then launch Docker Desktop and wait until the whale icon in the system
tray stops animating. Docker will not work until it does.

## 2. Run it

Open **PowerShell** (Start menu → type "PowerShell") and paste:

```powershell
docker run -p 5173:80 deepakhanal62/criiq:demo
```

The first run downloads about 1 GB, so give it a few minutes. Leave the window
open — closing it stops the app.

## 3. Open it

http://localhost:5173

```
Email:     rahul@criiq.local
Password:  coach1234
```

You can also register your own account from the sign-up screen.

To stop: press `Ctrl + C` in the PowerShell window.

---

## If something goes wrong

**"docker: command not found" / "cannot connect to the Docker daemon"**
Docker Desktop is not running. Start it, wait for the whale icon to settle, then
open a new PowerShell window.

**"port is already allocated"**
Something else is using port 5173. Use a different one — for example
`docker run -p 8080:80 deepakhanal62/criiq:demo` — then open http://localhost:8080.

**Simulation or optimisation requests are slow or time out**
They run a genetic algorithm and are CPU-heavy. In Docker Desktop go to
Settings → Resources and allow at least 4 CPUs and 8 GB of memory.

**No internet / the download is blocked**
Ask Dipa for the `criiq-images.tar.gz` file instead, then:
```powershell
docker load -i criiq-images.tar.gz
docker run -p 5173:80 deepakhanal62/criiq:demo
```
