package example.entity

import org.seasar.doma.Column
import org.seasar.doma.Entity
import org.seasar.doma.Id
import org.seasar.doma.Metamodel
import org.seasar.doma.Table

/** */
@Entity(metamodel = Metamodel())
@Table(schema = "public", name = "ledger")
class Ledger {

    /** */
    @Id
    @Column(name = "ledger_id")
    var ledgerId: Long = -1L
}
