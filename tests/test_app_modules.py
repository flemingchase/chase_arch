from pathlib import Path
import shutil
import tempfile
import unittest

import app_modules


class AppModuleTests(unittest.TestCase):
    def test_default_includes_rofi_chthm_and_support_without_optional_programs(self):
        selection = app_modules.resolve_selection()
        self.assertEqual(set(app_modules.CORE_APPS),
                         {'zsh', 'vim', 'qtile', 'ly', 'alacritty', 'qutebrowser', 'rofi', 'chthm'})
        self.assertTrue(set(app_modules.CORE_PACKAGES) <= set(selection.official))
        self.assertNotIn('chthm', selection.official)
        self.assertIn('qt6ct', selection.official)
        self.assertEqual(selection.optional, ())
        self.assertEqual(selection.aur, ())
        self.assertEqual(set(selection.components),
                         {'zsh', 'vim', 'qtile', 'alacritty', 'qutebrowser', 'rofi', 'qt6ct'})
        self.assertEqual(set(selection.targets), {'alacritty', 'qtile', 'qutebrowser', 'rofi', 'qt6ct'})
        excluded = {'zathura', 'clementine', 'sioyek-git', 'plymouth', 'firefox', 'librewolf',
                    'pcmanfm-qt', 'neovim', 'neovim-remote', 'base-devel', 'go',
                    'pipewire', 'networkmanager', 'fzf', 'scrot', 'xsel', 'xorg-xset', 'xorg-xrandr'}
        self.assertFalse(excluded & set(selection.official))

    def test_optional_dependencies_deduplicate_packages_and_configuration(self):
        selection = app_modules.resolve_selection(['pcmanfm-qt,qt6ct', 'pcmanfm-qt,zathura'])
        self.assertNotIn('qt6ct', selection.optional)
        self.assertEqual(selection.official.count('qt6ct'), 1)
        self.assertIn('adwaita-icon-theme', selection.official)
        self.assertIn('zathura-pdf-mupdf', selection.official)
        self.assertEqual(selection.components.count('pcmanfm-qt'), 1)
        self.assertTrue({'pcmanfm-qt', 'qt6ct', 'zathura'} <= set(selection.targets))
        self.assertNotIn('firefox', selection.components)

    def test_aur_tools_are_added_only_for_selected_aur_modules(self):
        selection = app_modules.resolve_selection(['clementine'])
        self.assertEqual(selection.aur, ('clementine',))
        self.assertTrue({'base-devel', 'go', 'qt6ct'} <= set(selection.official))
        self.assertIn('clementine', selection.components)
        self.assertNotIn('sioyek-git', selection.aur)
        with self.assertRaisesRegex(ValueError, '--no-aur conflicts'):
            app_modules.resolve_selection(['clementine'], no_aur=True)
        paru = app_modules.resolve_selection(['clementine'], aur_helper='paru')
        self.assertIn('base-devel', paru.official)
        self.assertNotIn('go', paru.official)

    def test_core_selections_and_librefox_alias_are_normalized(self):
        selection = app_modules.resolve_selection([' vim , librefox ', 'librewolf,qtile,rofi,chthm,qt6ct'])
        self.assertEqual(selection.optional, ('librewolf',))
        self.assertEqual(selection.official.count('vim'), 1)
        self.assertEqual(selection.official.count('librewolf'), 1)
        self.assertIn('librewolf', selection.components)

    def test_selecting_default_apps_and_support_does_not_change_the_plan(self):
        self.assertEqual(app_modules.resolve_selection(['rofi,chthm,qt6ct']),
                         app_modules.resolve_selection())

    def test_unknown_and_empty_selections_are_rejected(self):
        for groups in (['unknown-app'], [''], ['firefox,'], [',firefox'], ['firefox,,zathura']):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                app_modules.resolve_selection(groups)

    def test_dependency_cycles_in_custom_catalog_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'packages').mkdir()
            for name in ('core.txt', 'support.txt'):
                shutil.copy2(app_modules.ROOT / 'packages' / name, root / 'packages' / name)
            (root / 'packages/apps.toml').write_text('''schema_version = 1
[apps.first]
description = "First"
requires = ["second"]
[apps.second]
description = "Second"
requires = ["first"]
''')
            with self.assertRaisesRegex(ValueError, 'dependency cycle'):
                app_modules.resolve_selection(['first'], root=root)


if __name__ == '__main__':
    unittest.main()
