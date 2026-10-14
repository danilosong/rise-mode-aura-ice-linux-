# Rise Mode CPU Temp Driver para Ubuntu

Projeto Linux que reproduz a função encontrada no executável do pacote fornecido: monitorar temperaturas e uso do hardware e encaminhar uma mensagem HID ao visor/controlador reconhecido pelo software Windows.

## Identificação do pacote analisado

O arquivo `Rise Mode Aura Ice ARGB - Software para Windows -8.0.rar` contém um único instalador Inno Setup, identificado no próprio instalador como **Rise Mode Temp CPU Driver R2.2**. Ele instala uma aplicação .NET Framework 4.7.2 baseada no LibreHardwareMonitor, além de `SendTemp.exe` e `HidSharp.dll`. Portanto, o conteúdo não corresponde a um aplicativo de iluminação ARGB conforme o nome do RAR sugere.

Na implementação Windows analisada, o monitor lê sensores e prepara uma mensagem de 11 bytes. Os bytes 1 a 6 carregam, nesta ordem, temperatura da CPU, temperatura da GPU, uso da CPU, uso da memória, temperatura da placa-mãe e uso da GPU. `SendTemp.exe` lê essa mensagem num buffer HID de 24 bytes, deixando o restante zerado, e encaminha o buffer ao dispositivo identificado por VID `0xAA88` e PID `0x8666`.

Para o uso deste watercooler como visor da CPU, o envio Linux não depende de haver sensor de GPU: o campo de CPU continua sendo enviado mesmo quando o driver gráfico não fornece temperatura. Leituras de temperatura com salto de 25 °C ou mais só são aceitas depois de três amostras próximas entre si; uma leitura isolada anormal mantém temporariamente o último valor estável.

Esse projeto substitui a interface Windows por um painel web local e troca a leitura de hardware por sensores Linux em `/sys/class/hwmon`, `/proc/stat`, `/proc/meminfo` e `/sys/class/drm`. Ele só envia dados a dispositivos com o VID/PID vistos no executável. Não há evidência no pacote de comandos para alterar cores ou efeitos ARGB; por isso, o painel não apresenta esses controles.

## Requisitos

- Ubuntu com Python 3.10 ou mais recente.
- Acesso de leitura aos sensores do kernel em `/sys/class/hwmon`.
- Regra udev para o serviço de usuário acessar o dispositivo USB sem root.

O painel usa apenas a biblioteca padrão do Python. Primeiro instale a regra de acesso ao dispositivo HID; o Ubuntu pedirá sua senha administrativa:

```bash
./install-udev-rule.sh
```

Depois instale o serviço para iniciar a telemetria automaticamente em segundo plano ao entrar no Ubuntu:

```bash
./install-service.sh
```

O serviço monitora os sensores e atualiza o visor a cada segundo; não é necessário deixar o painel web aberto. Veja o estado e os logs:

```bash
systemctl --user status rise-mode-temp.service
journalctl --user -u rise-mode-temp.service -f
```

Execute esses comandos sem `sudo`; eles precisam se conectar ao barramento `systemd --user` da sua sessão.

Para remover o início automático:

```bash
./remove-service.sh
```

## Iniciar

```bash
python3 app.py
```

Para abrir o painel de acompanhamento em uma sessão, inicie também a interface web. Abra <http://127.0.0.1:8765>. Para escolher outra porta:

```bash
python3 app.py --host 127.0.0.1 --port 8765
```

O servidor escuta em `127.0.0.1` por padrão e não precisa de privilégios de root. Se o Ubuntu negar acesso HID, ajuste as permissões udev para o VID/PID `AA88:8666` e reconecte o dispositivo. Não execute o painel como root.

## Limites conhecidos

- A análise foi estática; não havia um controlador conectado para observar a comunicação em execução.
- A transferência de temperatura e o identificador USB são reproduzidos a partir do fluxo do executável. O envio HID ainda precisa ser validado com o hardware real.
- A seleção de sensores Linux é heurística. Algumas placas-mãe não expõem todos os sensores ou o uso da GPU pelo hwmon. A temperatura da GPU é opcional para exibir a CPU.
- Este projeto reproduz o monitoramento e a telemetria do pacote extraído. Não é um driver de iluminação ARGB.

## Estrutura

- `app.py`: leitura de sensores, pacote HID e servidor HTTP local.
- `static/index.html`: painel em português.
- `REVERSE_ENGINEERING.md`: inventário, evidências e limites da análise.
- `rise-mode-temp.service.in`: unidade systemd instalada pelo script.
- `install-udev-rule.sh`: configura acesso ao dispositivo HID uma única vez.
