filetype plugin indent on
filetype plugin on
syntax enable
set nocompatible
set showmatch
set ignorecase
set nohlsearch
set incsearch
set tabstop=4
set softtabstop=4
set expandtab
set shiftwidth=4
set autoindent
set number
set wildmode=longest,list
set textwidth=79
set cc=+1
set formatoptions+=t
set mouse=a
set clipboard=unnamedplus
set cursorline
set ttyfast
set noswapfile
set conceallevel=1
set wrap
set splitright

let maplocalleader=","
noremap <LocalLeader>s :split<CR>
noremap <LocalLeader>v :vsplit<CR>
noremap <silent> <c-h> <c-w>h
noremap <silent> <c-j> <c-w>j
noremap <silent> <c-k> <c-w>k
noremap <silent> <c-l> <c-w>l
noremap <LocalLeader>V :Vex<CR>

autocmd BufRead *.md,*.markdown,*.rst set filetype=markdown
autocmd BufWritePre * keeppatterns %s/\s\+$//e
highlight QuickFixLine gui=bold,underline cterm=bold,
            \underline guibg=NONE ctermbg=NONE guifg=NONE

if empty(v:servername) && exists('*remote_startserver')
      call remote_startserver('VIM')
endif

autocmd ColorScheme * highlight link texMathOper Normal
let maplocalleader =","
let g:tex_flavor='latex'
let g:vimtex_view_method = 'zathura'
let g:vimtex_view_use_temp_files = 1
let g:vimtex_compiler_latexmk = {
      \ 'options' : [
      \   '-verbose',
      \   '-emulate-aux-dir',
      \   '-file-line-error',
      \   '-synctex=1',
      \   '-interaction=nonstopmode',
      \ ],
      \}

let g:airline_theme='base16'
call plug#begin()
" Make sure you use single quotes
Plug 'lervag/vimtex'
Plug 'bling/vim-airline'
Plug 'vim-airline/vim-airline-themes'
Plug 'SirVer/ultisnips'
call plug#end()
