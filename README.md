Tested only  Linux Manjaro 26

use system settings > display > select resolution mod

Abaixo estão os **requisitos** e a **explicação de uso** do script `edid_live_override.py`.

## Requisitos

### Sistema

O script precisa de Linux com DRM/KMS ativo:

```text
/sys/class/drm/
/sys/kernel/debug/dri/
```

No seu caso já funcionou, então seu sistema atende.

### Permissões

Para apenas listar modos:

```bash
python3 edid_live_override.py --list
```

Para modificar/aplicar EDID runtime:

```bash
sudo python3 edid_live_override.py ...
```

Precisa de `sudo` porque ele escreve em:

```text
/sys/kernel/debug/dri/2/HDMI-A-2/edid_override
```

### Pacotes necessários

No Manjaro/Arch:

```bash
sudo pacman -S python xorg-xrandr
```

Opcional, para analisar EDID:

```bash
sudo pacman -S v4l-utils
```

Opcional, para extrair/parsear EDID antigo:

```bash
sudo pacman -S read-edid
```

### Python

Não precisa de `pip`.

O script usa apenas bibliotecas padrão do Python:

```text
argparse
math
os
re
subprocess
sys
time
dataclasses
pathlib
typing
```

Então basta ter:

```bash
python3
```

Conferir:

```bash
python3 --version
```

## Como usar

Entre na pasta:

```bash
cd ~/MONITOR
```

Dar permissão de execução:

```bash
chmod +x edid_live_override.py
```

### Listar os modos atuais do EDID

```bash
python3 edid_live_override.py --connector HDMI-A-2 --list
```

Ou autodetectando o monitor conectado:

```bash
python3 edid_live_override.py --list
```

### Adicionar uma resolução

Exemplo:

```bash
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '869x723:75' --clean-cta
```

Isso faz:

```text
ler EDID atual do sistema
limpar bloco CTA/HDMI falso
adicionar 869x723@75
corrigir checksum
aplicar EDID runtime no kernel
```

### Adicionar várias resoluções

Use aspas por causa do `;`:

```bash
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '1280x1024;869x723:75;1024x1024:75' --clean-cta
```

Sem `:Hz`, ele tenta `60` e `75`.

Exemplo:

```bash
--add '1280x1024'
```

vira tentativa de:

```text
1280x1024@60
1280x1024@75
```

Com `:75`:

```bash
--add '869x723:75'
```

ele adiciona só:

```text
869x723@75
```


### Resetar o override

Se quiser desfazer:

```bash
sudo python3 edid_live_override.py --connector HDMI-A-2 --reset
```

Ou reinicie o PC:

```bash
reboot
```

Esse override é temporário e some no reboot.

## Opções principais

```bash
--connector HDMI-A-2
```

Escolhe o conector DRM manualmente.

```bash
--add '869x723:75'
```

Adiciona resolução e Hz.

```bash
--clean-cta
```

Remove o bloco CTA/HDMI estranho antes de adicionar modos novos. No seu caso é recomendado.

```bash
--force
```

Força adicionar mesmo fora dos limites do monitor.

Exemplo:

```bash
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '900x1280:75' --clean-cta --force
```

Mas isso **não garante funcionar**. Só força o EDID a anunciar o modo.

```bash
--reset
```

Remove o override runtime.

```bash
--list
```

Lista modos atuais.

```bash
--default-refreshes '60,75'
```

Define quais Hz usar quando você não especificar `:Hz`.

Exemplo:

```bash
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '900x720' --default-refreshes '60,70,75' --clean-cta
```

## Exemplos prontos para seu monitor

### Modo seguro

```bash
cd ~/MONITOR
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '869x723:75' --clean-cta
```


### Modo quadrado

```bash
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '1024x1024:60' --clean-cta
```

Mais seguro que `1024x1024:75`.

### Usar o monitor em pé

Melhor não criar `1024x1280`. Use rotação:


## Limitações

O script não faz milagre físico.

Seu monitor declara:

```text
Horizontal: 31–80 kHz
Vertical:   56–75 Hz
Pixel clock máximo: 140 MHz
```

Então resoluções como:

```text
900x1280@75
800x1280@75
1024x1280@75
```

passam de `80 kHz` horizontal e provavelmente não funcionam.

O script pode até forçar com `--force`, mas o monitor pode mostrar:

```text
out of range
sem sinal
tela preta
imagem piscando
```

## Comando mais útil para você

```bash
cd ~/MONITOR
sudo python3 edid_live_override.py --connector HDMI-A-2 --add '869x723:75;1024x1024:60' --clean-cta
```
