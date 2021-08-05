from glob import glob
from tqdm import tqdm
from pathlib import Path
from jinja2 import Template, Environment, FileSystemLoader
#from markdown import markdown
#import marko
from marko.ext.gfm import gfm as marko
import markdown
import re
import yaml
import os, shutil
import importlib
import pickle, json
import datetime
from time import sleep

#from rich.progress import track as tqdm
tqdm = lambda x: x
from rich.console import Console
console = Console()

from typing import Dict, List, TypedDict
class ConfigType(TypedDict):
    ROOT_FOLDER: str
    PUBLIC_FOLDER: str
    BASE_URL: str
    PROTOCOL: str
    includes: List[str]
    extensions: List[str]

class FileMetaType(TypedDict):
    route: str
    title: str
    template: str
    author: str
    summary: str
    date: str

class FileType(TypedDict):
    filename: str
    content: str

class FileStartType(FileType):
    meta: str

class FilePreType(FileType):
    meta: FileMetaType

class FilePostType(FileType):
    meta: FileMetaType

class FileEndType(FileType):
    meta: FileMetaType
    dest_filename: str
    dest_folder: str

class WrongMarkdownFileException(Exception):
    def __init__(self, filename=None, markdown=None):
        self.filename = filename
        self.markdown = markdown
        if self.filename is not None:
            self.message = f'ERROR: Markdown file is wrong ({self.filename})'
        else:
            self.message = f'ERROR: Markdown is wrong.'
        super().__init__(self.message)


class Generator:

    def __init__(self, config : ConfigType):

        self.config = config
        self.config['GENERATION_TIME'] = datetime.date.today().strftime('%Y-%m-%d')

        self.includes = []
        if 'includes' in config:
            self.includes = config['includes']

        self.extensions = []
        if 'extensions' in config:
            self.extensions = config['extensions']
            
    # Function that injects config constants into template/content
    def inject_constants(self, constants, content):
        for key, value in constants.items():
            if isinstance(value, str) or str(value).replace('.','',1).isnumeric():
                content = content.replace(f'~~{key}~~', value)
        return content
    
    def get_md_files(self):
        return [f for f in glob(f'{self.config["ROOT_FOLDER"]}/*.md')] + [f for f in glob(f'{self.config["ROOT_FOLDER"]}/+*/*.md')]
    
    def read_markdown_string(self, md_string):
        md_string = f'\n{md_string}'
        anchors = list(re.finditer('\r?\n-+\r?\n', md_string))
        if len(anchors) >= 2:
            meta = md_string[anchors[0].end():anchors[1].start()]
            content = md_string[anchors[1].end():]
        else:
            raise WrongMarkdownFileException
        return (content, meta)
    
    def read_markdown_file(self, md_filename):
        try:
            with open(md_filename, 'rt') as f:
                md_string = f.read()
                return self.read_markdown_string(md_string)
        except WrongMarkdownFileException as ex:
            raise WrongMarkdownFileException(md_filename)

    def _get_extensions(self, conf, path):
        extensions = []
        if 'extensions' in conf:
            for ext_filename in conf['extensions']:
                spec = importlib.util.spec_from_file_location("", f'{path}/{ext_filename}')
                ext = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ext)
                extension_class_name = [xx for xx in ext.__dict__ if "Extension" in xx][-1]
                extension_class = getattr(ext, extension_class_name)
                ext_instance = extension_class()
                extensions.append(ext_instance)
        return extensions

    # def md2html(self, md):
    #     return marko.convert(md)

    def md2html(self, md):
        
        converter = markdown.Markdown(
            extensions=[
                # TODO: Przenieść do pliku konfiguracyjnego
                'toc',
                'fenced_code',
                'codehilite',
                'markdown.extensions.footnotes',
                'markdown.extensions.attr_list',
                'markdown.extensions.def_list',
                'markdown.extensions.tables',
                'markdown.extensions.abbr',
                'markdown.extensions.md_in_html'
                #'pymdownx.tabbed' # umozliwia tworzenie kart - nie działa lub działa kiepsko z bootstrap
                ,'pymdownx.arithmatex' # mathJax
                ,'pymdownx.caret' # superscript -> text^a\ superscript^
                ,'pymdownx.details' # pozwala wygenerowac rozwijane szczegoly, przyklad:
                # ??? optional-class "Summary"
                # Here's some content.
                #,'pymdownx.emoji' # trzeba sprawdzić licencje providerow tych ikonek
                #,'pymdownx.escapeall' # pozwala stawiac \ przed wszystkimi znakami: \W\e\ \c\a\n\ \e\s\c\a\p\e
                #,'pymdownx.extra' # ficzery ktore byly w Markdown, ale teraz są przepisane ponownie ze wzgledu na kompatybilnosc a raczej jej brak
                ,'pymdownx.highlight' # kolorowanie: `#!php-inline $a = array("foo" => 0, "bar" => 1);`
                ,'pymdownx.keys' # możliwosć dodawania skrótów klawiszowych: ++ctrl+alt+delete++
                ,'pymdownx.magiclink' # automatycznie wykrywa i wstawia <a href=".."> w miejsce gdzie sa linki
                ,'pymdownx.mark' # podkresla tekst jakby markerem
                ,'pymdownx.progressbar'  # progressBar [=25% "25%"]
                #,'pymdownx.superfences'
                ,'pymdownx.tasklist' # umozliwia tworzenie listy zadan
                ,'pymdownx.tilde' # umozliwia pisanie indeksu dolnego badz przekreslonego tekstu
            ],
            extension_configs={
                "pymdownx.arithmatex": {
                    'smart_dollar': False,
                    'preview': False
                },
                'codehilite': {
                    'use_pygments': False
                }
            }
        )

        html = converter.convert(md)
        toc = converter.toc_tokens

        html = (
            html
            .replace('<table>', '<table class="table table-striped table-hover">')
            .replace('th align="center"', 'th style="text-align: center"')
            .replace('th align="right"', 'th style="text-align: right"')
        )
        return html, toc

    def get_extensions(self, conf):
        return self._get_extensions(conf, f'./extensions')
    
    def generate(self):
        with console.status('[bold green] Generating...'):
            template_env = Environment(loader=FileSystemLoader(f'{self.config["ROOT_FOLDER"]}/'))
            shutil.rmtree(f'{self.config["PUBLIC_FOLDER"]}', ignore_errors=True)
            for incl in self.includes:
                if os.path.isdir(f'{self.config["ROOT_FOLDER"]}/{incl}'):
                    shutil.rmtree(f'{self.config["PUBLIC_FOLDER"]}/{incl}', ignore_errors=True)
                    shutil.copytree(f'{self.config["ROOT_FOLDER"]}/{incl}', f'{self.config["PUBLIC_FOLDER"]}/{incl}') # , dirs_exist_ok=True
                else:
                    shutil.copy(f'{self.config["ROOT_FOLDER"]}/{incl}', f'{self.config["PUBLIC_FOLDER"]}/{incl}')

            # Read all files and store in list
            md_files = self.get_md_files()
            self.all_files = []
            for md_file in tqdm(md_files):
                content_str, meta_str = self.read_markdown_file(md_file)

                meta_raw = yaml.load(meta_str, Loader=yaml.Loader)

                #meta_hash = hashlib.md5(meta_str.encode()).hexdigest()
                #content_hash = hashlib.md5(content_str.encode()).hexdigest()

                self.all_files.append({
                    'filename': md_file,
                    # 'meta_hash': meta_hash,
                    # 'content_hash': content_hash,
                    'content': content_str,
                    'meta': meta_raw
                })

            # Execute on_generation_start (global extensions)
            # TODO: Uruchamiać przy edycji, zmianie rozszerzeń.
            for extension in self.get_extensions({'extensions':self.extensions}):
                on_generation_start = getattr(extension, 'on_generation_start', None)  
                if on_generation_start is not None:
                    extension.on_generation_start(self, self.config, self.all_files)

            
            # Preparing config constants
            # TODO: Poniższe to tylko podmianka np. ~~BASE_URL~~ 
            # na URL podany w configu glownym
            for file in tqdm(self.all_files):
                #file['md_content'] = 
                file['meta'] = {
                    key:self.inject_constants(self.config, value) if isinstance(value, str) else value 
                    for key, value in file['meta'].items()
                }
                file['content'] = self.inject_constants(self.config, file['content'])

            for extension in self.get_extensions({'extensions':self.extensions}):
                preprocessing = getattr(extension, 'preprocessing', None)  
                if preprocessing is not None:
                    extension.preprocessing(self, self.config, self.all_files)

            for file in tqdm(self.all_files):
                file['meta'] = file['meta']
                # TODO: Generowanie HTMLa / parsowanie markdowna
                body, toc = self.md2html(file['content'])
                file['meta']['toc'] = toc

                # Processing template file
                if 'template' in file['meta']:
                    tpl_filename = f'{self.config["ROOT_FOLDER"]}/' + file['meta']['template']
                elif Path(file['filename'].replace('.md', '.html')).exists():
                    tpl_filename = file['filename'].replace('.md', '.html')
                else:
                    raise Exception(f'ERROR: There is no template for {file["filename"]}')

                if Path(tpl_filename).exists():
                    with open(tpl_filename, 'rt') as f:
                        tpl = f.read()
                else:
                    raise Exception(f'ERROR: There is no template in {tpl_filename}')

                # Generate HTML
                #tpl = self.inject_constants(self.config, tpl)
                template = template_env.from_string(tpl)
                html = template.render({ # process template
                    **{
                        'body': body,
                        'config': self.config,
                        'meta': file['meta']
                    },
                })

                template = template_env.from_string(html)
                html = template.render({ # process template instructions embedded in markdown
                    **{
                    'config': self.config,
                    'meta': file['meta']
                    }
                })
                file['content'] = html

            for extension in self.get_extensions({'extensions':self.extensions}):
                postprocessing = getattr(extension, 'postprocessing', None)  
                if postprocessing is not None:
                    pass
                    extension.postprocessing(self, self.config, self.all_files)

            for file in tqdm(self.all_files):
                # get destination folder
                dest_filename = file['meta']['route'].replace(self.config['BASE_URL'], '')
                dest_filename = re.sub(r'^/', '', dest_filename) # remove / from begining
                dest_filename = f'{self.config["PUBLIC_FOLDER"]}/' + dest_filename # add website output path
                if not '.html' in dest_filename: # add index.html if file name is not specified
                    dest_filename += '/index.html'
                dest_folder = os.path.dirname(dest_filename)

                # make dest. directory
                os.makedirs(dest_folder, exist_ok=True)
                
                # save file
                with open(f'{dest_filename}', 'wt') as f:
                    f.write(file['content'])

                file['dest_filename'] = dest_filename
                file['dest_folder'] = dest_folder

            # Execute on_generation_end for each extension
            for extension in self.get_extensions({'extensions':self.extensions}):
                on_generation_end = getattr(extension, 'on_generation_end', None)  
                if on_generation_end is not None:
                    pass
                    extension.on_generation_end(self, self.config, self.all_files)

            
            with open(f'{self.config["PUBLIC_FOLDER"]}/pages.pickle', 'wb') as f:
                pickle.dump(self.all_files, f, pickle.HIGHEST_PROTOCOL)
