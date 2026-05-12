# Backend command plan

## Login status
wsl.exe -d Ubuntu lgogdownloader --check-login-status

## Login
wsl.exe -d Ubuntu lgogdownloader --login

## GUI login
wsl.exe -d Ubuntu lgogdownloader --gui-login

## Update backend cache
wsl.exe -d Ubuntu lgogdownloader --update-cache

## List library
wsl.exe -d Ubuntu lgogdownloader --list

## Download single game without extras
wsl.exe -d Ubuntu lgogdownloader --download --game <slug> --exclude extras
