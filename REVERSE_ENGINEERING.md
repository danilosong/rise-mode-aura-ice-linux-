# Relatório de engenharia reversa

## Artefato e cadeia de extração

- RAR fornecido: `Rise Mode Aura Ice ARGB - Software para Windows -8.0.rar`.
- O inventário RAR mostrou um único membro: `Rise Mode Aura Ice ARGB - Software para Windows -8.0.exe` (8.611.443 bytes).
- SHA-256 do instalador: `c07f925ada7bb7cd658a105a225a3b21bb2f122af121e9280284d65bd8289dbe`.
- O EXE é um instalador PE32 x86 feito com Inno Setup 6.1.0.
- O conteúdo do instalador identifica o produto como `Rise Mode Temp CPU Driver R2.2`. Inclui o aplicativo principal, `SendTemp.exe`, `CPU Server.exe`, `HidSharp.dll`, `LibreHardwareMonitorLib.dll` e `PawnIO_setup.exe`.
- O aplicativo principal é um assembly .NET Framework 4.7.2 AnyCPU; usa Windows Forms e deriva do LibreHardwareMonitor. `SendTemp.exe` também é .NET Framework 4.7.2 e contém P/Invokes para a API HID do Windows.

## Evidências estáticas usadas

- REA `inspect_artifact`, Evidence `ev_b32ce655cfc681c85cf46eaa9b0e066b368bccd1a08eded268db32a39e29c57d`: o executável de entrada é PE, sem arquivos filhos incorporados. A inspeção do RAR foi feita com libarchive e a extração do instalador com `innoextract`.
- REA `inspect_managed_artifact`, Evidence `ev_7e69b4dd91d00ef7b6ec9a1585e5669ac300de2f6ea872e54c19d9d388c7a766`: identidade, framework e referências do aplicativo principal.
- REA `inspect_managed_members`, Evidence `ev_9d8d1726ad9e6802ba218fc4d2365b765831b7ec197f52655e0c3c1dc8e10960`: metadados e métodos de `SendTemp.exe`.
- REA `inspect_managed_native_boundaries`, Evidence `ev_e35357a72b21b651a614ce37e99a6330c010214df31599874f9becdbf4ccd5af`: P/Invoke e limite HID declarado por `SendTemp.exe`.
- A leitura estática do IL mostra que `MainForm` cria `btPipSnd` com 11 bytes. `Timer_Tick` preenche os índices 1–6 e escreve a mensagem no named pipe `tifPipe`; índices 0 e 7–10 ficam zerados.
- `SendTemp.exe` lê a mensagem num buffer de 24 bytes e escreve esse buffer completo no HID, portanto os bytes 11–23 também ficam zerados. O método `InitialHid` procura VID `43656` (`0xAA88`) e PID `34406` (`0x8666`).

## Fatos, inferências e incógnitas

**Observado:** o software Windows coleta temperaturas e percentuais de CPU, GPU, memória e placa-mãe; envia uma mensagem de 11 bytes por named pipe a um processo auxiliar; o auxiliar a coloca num buffer HID de 24 bytes e encaminha o buffer ao dispositivo com VID/PID fixos.

**Inferido:** o dispositivo associado é o visor/controlador de telemetria do conjunto de refrigeração. O nome do RAR menciona ARGB, mas o executável extraído não apresenta uma interface nem comandos de cores/efeitos RGB nas rotinas inspecionadas.

**Desconhecido:** a interpretação do firmware para todos os bytes reservados, compatibilidade com revisões distintas do produto e resposta física ao pacote. Não foi feita captura em execução nem teste com o hardware conectado. O envio no Linux, portanto, deve ser validado pelo usuário no dispositivo real.

## Nota de segurança e distribuição

O executável original e as DLLs proprietárias não foram copiados para este projeto. O código Linux foi escrito de forma independente a partir do formato de telemetria e dos identificadores observados. A licença incluída no instalador refere-se a componentes de terceiros e não foi tratada como autorização para redistribuir os binários do fabricante.
