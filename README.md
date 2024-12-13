# MongoRx 2.0
Porting [MongoRx](https://github.com/mongodb-developer/MongoRx/tree/main)'s App Services/GraphQL backend to FARM and MongoRx's Angular-based UI to React+[LeafyGreenUI](https://github.com/mongodb/leafygreen-ui)

## Setup Python Virtual Environment

```bash
cd backend
python3 -m venv .
source ./bin/activate
```

```bash
# install pip-compile
python3 -m pip install pip-tools

# re-create requirements.txt
rm requirements.txt
./bin/pip-compile
pip3 install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cpu

```

## Install Dependencies

```bash
pip3 install -r requirements.txt
```

## Configure

```bash
cp ./.envrc.example ./.envrc
```

Edit the `DB_URL` and `DB_NAME` environment variables in `.envrc` and export them (**tip:** enclose the value of the `DB_URL` variable in quotes.)

```bash
source ./.envrc
```
