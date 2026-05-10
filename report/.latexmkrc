$pdf_mode      = 4;          # 4 = lualatex
$lualatex      = 'lualatex -interaction=nonstopmode -file-line-error -halt-on-error %O %S';
$xelatex       = 'xelatex  -interaction=nonstopmode -file-line-error -halt-on-error %O %S';
$bibtex_use    = 2;          # always run biber/bibtex when needed
$biber         = 'biber --validate-datamodel %O %S';
$clean_ext     = 'bbl bcf run.xml synctex.gz';

# Per-language switch: zh uses xelatex
sub use_xelatex_for_zh {
    if ($_[0] =~ m{(?:^|/)zh/}) {
        $pdf_mode = 1;       # 1 = pdflatex via $latex; we abuse to drive xelatex below
    }
}
